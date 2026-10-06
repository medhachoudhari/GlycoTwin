import pandas as pd
import numpy as np
import os
import sys
import argparse
import tempfile
from pathlib import Path

def print_section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")

def is_interpolated(series):
    """
    Diagnostic to see if glucose values appear interpolated.
    Returns True if more than 1% of non-NaN values have a non-zero fractional part.
    """
    not_na = series.dropna()
    if len(not_na) == 0:
        return False
    # Typical mg/dL values are integers. Check for fractional parts > 1e-5.
    fractional = not_na % 1
    frac_count = (fractional > 1e-5).sum()
    return frac_count > 0.01 * len(not_na)

def audit_dataset(data_dir):
    data_path = Path(data_dir)
    if not data_path.exists() or not data_path.is_dir():
        print(f"Error: Directory '{data_dir}' does not exist.")
        sys.exit(1)
    
    csv_files = list(data_path.rglob("*.csv"))
    # The dataset contains participant CSV files, plus others like bio.csv, microbes.csv
    # We target files starting with "CGMacros-" to capture the 45 participants
    participant_files = [f for f in csv_files if "CGMacros-" in f.name]
    
    if len(participant_files) == 0:
        print(f"Error: No participant CSV files found in '{data_dir}'.")
        sys.exit(1)
        
    print(f"[EMPIRICAL OBSERVATION] Found {len(participant_files)} participant CSV files.")
    
    total_rows = 0
    total_meal_events = 0
    total_glucose_rows = 0
    
    meal_spellings = {}
    
    macro_cols = ['Calories', 'Carbs', 'Protein', 'Fat', 'Fiber', 'Amount Consumed']
    glucose_cols = ['Libre GL', 'Dexcom GL']
    
    missingness = {col: 0 for col in macro_cols + glucose_cols}
    
    timestamp_steps = {}
    total_gaps = 0
    total_duplicates = 0
    
    interpolated_libre = 0
    interpolated_dexcom = 0
    
    window_completeness = {
        'Libre GL': [],
        'Dexcom GL': []
    }
    
    meal_spacing = []
    
    for p_file in participant_files:
        try:
            df = pd.read_csv(p_file)
        except Exception as e:
            print(f"Error reading {p_file.name}: {e}")
            sys.exit(1)
            
        # Standardize column names (e.g., remove trailing spaces in 'Amount Consumed ')
        df.columns = [c.strip() for c in df.columns]
        
        if 'Timestamp' not in df.columns:
            print(f"Error: 'Timestamp' column missing in {p_file.name}")
            sys.exit(1)
            
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        
        total_rows += len(df)
        
        has_libre = 'Libre GL' in df.columns
        has_dexcom = 'Dexcom GL' in df.columns
        
        # Determine interpolated signals
        if has_libre:
            missingness['Libre GL'] += df['Libre GL'].isna().sum()
            if is_interpolated(df['Libre GL']):
                interpolated_libre += 1
        else:
            missingness['Libre GL'] += len(df)
            
        if has_dexcom:
            missingness['Dexcom GL'] += df['Dexcom GL'].isna().sum()
            if is_interpolated(df['Dexcom GL']):
                interpolated_dexcom += 1
        else:
            missingness['Dexcom GL'] += len(df)
                
        # Rows with at least one glucose reading
        if has_libre and has_dexcom:
            total_glucose_rows += df[['Libre GL', 'Dexcom GL']].notna().any(axis=1).sum()
        elif has_libre:
            total_glucose_rows += df['Libre GL'].notna().sum()
        elif has_dexcom:
            total_glucose_rows += df['Dexcom GL'].notna().sum()
            
        # Timestamp metrics (sort just in case)
        df = df.sort_values('Timestamp')
        diffs = df['Timestamp'].diff().dropna()
        for diff in diffs:
            mins = diff.total_seconds() / 60.0
            if mins <= 0:
                total_duplicates += 1
            else:
                timestamp_steps[mins] = timestamp_steps.get(mins, 0) + 1
                if mins > 1.0: # Gap defined as > 1 min
                    total_gaps += 1
                    
        # Meal events and post-meal windows
        if 'Meal Type' in df.columns:
            meal_rows = df[df['Meal Type'].notna()]
            total_meal_events += len(meal_rows)
            
            for m in meal_rows['Meal Type']:
                meal_spellings[m] = meal_spellings.get(m, 0) + 1
                
            for col in macro_cols:
                if col in df.columns:
                    missingness[col] += meal_rows[col].isna().sum()
                else:
                    missingness[col] += len(meal_rows)
                    
            meal_times = meal_rows['Timestamp'].tolist()
            if len(meal_times) > 1:
                spaces = [(t2 - t1).total_seconds() / 3600.0 for t1, t2 in zip(meal_times[:-1], meal_times[1:]) if pd.notna(t1) and pd.notna(t2)]
                # Filter out negative spaces which might happen if multiple meals have the exact same time
                spaces = [s for s in spaces if s > 0]
                meal_spacing.extend(spaces)
                
            # Completeness of 2-hour window (121 expected readings for 1-minute steps)
            df_indexed = df.set_index('Timestamp')
            for t in meal_times:
                if pd.isna(t):
                    continue
                end_t = t + pd.Timedelta(hours=2)
                window = df_indexed.loc[t:end_t]
                
                if has_libre:
                    complete_libre = window['Libre GL'].notna().sum()
                    window_completeness['Libre GL'].append((complete_libre, 121))
                if has_dexcom:
                    complete_dexcom = window['Dexcom GL'].notna().sum()
                    window_completeness['Dexcom GL'].append((complete_dexcom, 121))
                    
    # Printing Aggregate Results
    print_section("1. Overview (Documented vs Observed Facts)")
    print(f"[DOCUMENTED FACT] Expected 45 participant CSV files.")
    print(f"[EMPIRICAL OBSERVATION] Processed {len(participant_files)} participant files.")
    print(f"[DOCUMENTED FACT] Expected ~687,580 time-series rows, 1,706 rows with non-null Meal Type, and 687,580 rows with at least one glucose reading.")
    print(f"[EMPIRICAL OBSERVATION] Total Time-Series Rows = {total_rows}")
    print(f"[EMPIRICAL OBSERVATION] Total Rows with non-null Meal Type = {total_meal_events}")
    print(f"[EMPIRICAL OBSERVATION] Total Rows with >= 1 Glucose Reading = {total_glucose_rows}")
    
    print_section("2. Meal Label Spellings & Normalized Category Counts")
    print("[DOCUMENTED FACT] Meal Type indicates a meal start and identifies the meal.")
    normalized_counts = {}
    for raw_label, count in sorted(meal_spellings.items(), key=lambda x: -x[1]):
        print(f"  - Raw spelling: '{raw_label}' -> {count} occurrences")
        norm = str(raw_label).strip().lower()
        normalized_counts[norm] = normalized_counts.get(norm, 0) + count
        
    print("\n[EMPIRICAL OBSERVATION] Normalized Categories:")
    for norm_label, count in sorted(normalized_counts.items(), key=lambda x: -x[1]):
        print(f"  - '{norm_label}': {count}")
        
    print_section("3. Missingness")
    print("[DOCUMENTED FACT] Amount Consumed is an estimated percentage of the meal consumed.")
    print("[EMPIRICAL OBSERVATION] Missingness is calculated over all rows for Glucose, and over Meal rows for Macros/Amount Consumed.")
    for col in macro_cols:
        v = missingness[col]
        pct = (v / total_meal_events * 100) if total_meal_events else 0
        print(f"  - {col}: {v} missing meal rows ({pct:.2f}%)")
        
    for col in glucose_cols:
        v = missingness[col]
        pct = (v / total_rows * 100) if total_rows else 0
        print(f"  - {col}: {v} missing total rows ({pct:.2f}%)")
            
    print_section("4. Timestamps & Time-Series Quality")
    print(f"[EMPIRICAL OBSERVATION] Total Duplicate Timestamp Steps (<= 0s diff): {total_duplicates}")
    print(f"[EMPIRICAL OBSERVATION] Total Gaps (> 1 min step): {total_gaps}")
    
    if timestamp_steps:
        most_common_step = max(timestamp_steps.items(), key=lambda x: x[1])
        print(f"[EMPIRICAL OBSERVATION] Most common timestamp step: {most_common_step[0]} minutes (Occurrences: {most_common_step[1]})")
    
    print_section("5. Assessment of Interpolation in Glucose Channels")
    print("[DOCUMENTED FACT] CGM values are in mg/dL.")
    print("[INFERENCE] Standard CGM devices typically report integer mg/dL values. The presence of numerous fractional values strongly suggests the data has been interpolated to fit a regular time grid.")
    
    print(f"[EMPIRICAL OBSERVATION] Libre GL shows strong signs of interpolation in {interpolated_libre} out of {len(participant_files)} files.")
    print(f"[EMPIRICAL OBSERVATION] Dexcom GL shows strong signs of interpolation in {interpolated_dexcom} out of {len(participant_files)} files.")
        
    print_section("6. Meal Spacing & Post-Meal Window Completeness")
    if meal_spacing:
        print(f"[EMPIRICAL OBSERVATION] Meal Spacing: Mean = {np.mean(meal_spacing):.2f} hours, Median = {np.median(meal_spacing):.2f} hours")
    else:
        print("[EMPIRICAL OBSERVATION] Meal Spacing: Not enough meals to compute.")
        
    def summarize_completeness(comp_list, name):
        if not comp_list:
            print(f"[EMPIRICAL OBSERVATION] {name} 2-Hour Windows: No data.")
            return
        actual = sum(c[0] for c in comp_list)
        expected = sum(c[1] for c in comp_list)
        pct = (actual / expected * 100) if expected else 0
        
        avg_readings = np.mean([c[0] for c in comp_list])
        print(f"[EMPIRICAL OBSERVATION] {name} 2-Hour Windows: {pct:.2f}% overall completeness.")
        print(f"                          Average of {avg_readings:.1f} / 121 expected readings per post-meal window.")
        
    summarize_completeness(window_completeness['Libre GL'], 'Libre GL')
    summarize_completeness(window_completeness['Dexcom GL'], 'Dexcom GL')

def test_audit():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a synthetic dataset
        df = pd.DataFrame({
            'Timestamp': pd.date_range('2020-01-01 08:00', periods=10, freq='1min'),
            'Libre GL': [100.0, 100.1, 100.2, 100.3, np.nan, 105.0, 106.0, 107.0, 108.0, 109.0], # Has fractional parts -> interpolated
            'Dexcom GL': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            'Meal Type': ['Breakfast', np.nan, np.nan, np.nan, 'Lunch ', np.nan, np.nan, np.nan, np.nan, np.nan],
            'Calories': [300, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
            'Amount Consumed ': [1.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
        })
        os.makedirs(os.path.join(tmpdir, "CGMacros-test"))
        df.to_csv(os.path.join(tmpdir, "CGMacros-test", "CGMacros-test.csv"), index=False)
        
        print("\n" + "*"*40)
        print("RUNNING TESTS ON SYNTHETIC DATA")
        print("*"*40)
        audit_dataset(tmpdir)
        print("*"*40)
        print("TESTS COMPLETED SUCCESSFULLY")
        print("*"*40 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit GlycoTwin meal events dataset.")
    parser.add_argument("--test", action="store_true", help="Run tests on a synthetic dataset instead of the real dataset.")
    parser.add_argument("--data-dir", type=str, default="data/raw/CGMacros", help="Path to the directory containing CGMacros participant CSVs.")
    
    args = parser.parse_args()
    
    if args.test:
        test_audit()
    else:
        audit_dataset(args.data_dir)
