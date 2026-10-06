"""
Data loading and meal event extraction module.

Limitations:
- Native versus interpolated Dexcom observations cannot currently be distinguished 
  from the available data and documentation. The extracted CGM windows preserve 
  all 1-minute interpolated values (including missing data/NaNs) without any 
  attempted resampling or downsampling.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any

def load_participant_data(filepath: Path | str) -> pd.DataFrame:
    """Load a participant CSV and normalize columns and meal labels."""
    df = pd.read_csv(filepath)
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]
    
    if 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
    
    # Normalize meal labels while preserving the original
    if 'Meal Type' in df.columns:
        # Create a normalized version
        # Some values might be NaN, so we handle that
        mask = df['Meal Type'].notna()
        df['Normalized Meal Type'] = pd.Series(dtype='object')
        df.loc[mask, 'Normalized Meal Type'] = df.loc[mask, 'Meal Type'].astype(str).str.strip().str.lower()
        
    return df

def extract_meal_events(
    df: pd.DataFrame, 
    max_cgm_gap_minutes: int = 15,
    cgm_col: str = 'Dexcom GL'
) -> List[Dict[str, Any]]:
    """
    Extract meal events with timestamps and available macronutrients,
    along with the 2-hour post-meal CGM window.
    
    Validates timestamp ordering, duplicates, CGM gaps, and window completeness.
    Does not include 'Amount Consumed' as a feature.
    """
    if df.empty or 'Timestamp' not in df.columns or 'Meal Type' not in df.columns:
        return []
        
    # Validate timestamp ordering and duplicates
    df = df.sort_values('Timestamp')
    time_diffs = df['Timestamp'].diff().dropna().dt.total_seconds()
    if (time_diffs <= 0).any():
        raise ValueError("Data contains duplicate or non-monotonic timestamps.")
        
    events = []
    meal_rows = df[df['Meal Type'].notna()]
    df_indexed = df.set_index('Timestamp')
    
    macro_cols = ['Calories', 'Carbs', 'Protein', 'Fat', 'Fiber']
    
    for _, row in meal_rows.iterrows():
        t = row['Timestamp']
        if pd.isna(t):
            continue
            
        end_t = t + pd.Timedelta(hours=2)
        window = df_indexed.loc[t:end_t]
        
        if cgm_col not in window.columns:
            continue
            
        valid_cgm = window[cgm_col].dropna()
        if len(valid_cgm) < 2:
            continue
            
        # Validate CGM gaps between actual readings
        gap_diffs = valid_cgm.index.to_series().diff().dropna().dt.total_seconds() / 60.0
        if not gap_diffs.empty and gap_diffs.max() > max_cgm_gap_minutes:
            continue # Gap exceeds maximum allowed, skip this meal
            
        # Validate 2-hour window completeness
        # The window should span at least close to 120 minutes (e.g. 115 min)
        window_duration = (valid_cgm.index[-1] - t).total_seconds() / 60.0
        if window_duration < 115:
            continue # Incomplete post-meal window
            
        event = {
            'Timestamp': t,
            'Original Meal Type': row['Meal Type'],
            'Normalized Meal Type': row.get('Normalized Meal Type', np.nan),
        }
        
        # Extract available macronutrients (excluding 'Amount Consumed')
        for mc in macro_cols:
            event[mc] = row[mc] if mc in row else np.nan
            
        event['CGM_Window'] = window[cgm_col].tolist()
        
        events.append(event)
        
    return events
