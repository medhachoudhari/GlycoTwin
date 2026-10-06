import pandas as pd
import numpy as np
import pytest
import tempfile
from pathlib import Path
from glycotwin.data.meals import load_participant_data, extract_meal_events

@pytest.fixture
def synthetic_participant_csv():
    # Create a synthetic dataset with valid ordering
    # We include some 'Amount Consumed ' (with space) to test column normalization
    df = pd.DataFrame({
        'Timestamp': pd.date_range('2026-01-01 08:00', periods=130, freq='1min'),
        'Dexcom GL': np.linspace(100, 150, 130), # 130 min of data
        'Meal Type': ['Breakfast'] + [np.nan] * 129,
        'Calories': [350] + [np.nan] * 129,
        'Amount Consumed ': [1.0] + [np.nan] * 129,
    })
    
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
        f.close()
        df.to_csv(f.name, index=False)
        yield Path(f.name)
        Path(f.name).unlink()

def test_load_participant_data(synthetic_participant_csv):
    df = load_participant_data(synthetic_participant_csv)
    
    # Check column normalization
    assert 'Amount Consumed' in df.columns
    assert 'Amount Consumed ' not in df.columns
    
    # Check meal label normalization
    assert 'Normalized Meal Type' in df.columns
    assert df.loc[0, 'Normalized Meal Type'] == 'breakfast'
    assert pd.isna(df.loc[1, 'Normalized Meal Type'])

def test_extract_meal_events_success():
    df = pd.DataFrame({
        'Timestamp': pd.date_range('2026-01-01 08:00', periods=130, freq='1min'),
        'Dexcom GL': np.linspace(100, 150, 130),
        'Meal Type': ['Breakfast'] + [np.nan] * 129,
        'Normalized Meal Type': ['breakfast'] + [np.nan] * 129,
        'Calories': [350] + [np.nan] * 129,
    })
    
    events = extract_meal_events(df, max_cgm_gap_minutes=15)
    assert len(events) == 1
    
    event = events[0]
    assert event['Original Meal Type'] == 'Breakfast'
    assert event['Normalized Meal Type'] == 'breakfast'
    assert event['Calories'] == 350
    assert 'Amount Consumed' not in event
    
    # Check that the full 1-minute window is preserved (no downsampling)
    # The window is 2 hours (121 minutes inclusive)
    assert len(event['CGM_Window']) == 121
def test_extract_meal_events_duplicate_timestamps():
    df = pd.DataFrame({
        'Timestamp': ['2026-01-01 08:00', '2026-01-01 08:00'],
        'Dexcom GL': [100, 101],
        'Meal Type': ['Breakfast', np.nan]
    })
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    
    with pytest.raises(ValueError, match="duplicate or non-monotonic"):
        extract_meal_events(df)
        
def test_extract_meal_events_gaps():
    # Create a gap of 40 minutes (exceeds max_cgm_gap_minutes=15)
    times = list(pd.date_range('2026-01-01 08:00', periods=60, freq='1min'))
    times.extend(list(pd.date_range('2026-01-01 09:40', periods=60, freq='1min'))) # 40 minute gap
    
    df = pd.DataFrame({
        'Timestamp': times,
        'Dexcom GL': np.ones(len(times)) * 100,
        'Meal Type': ['Breakfast'] + [np.nan] * (len(times) - 1)
    })
    
    events = extract_meal_events(df, max_cgm_gap_minutes=15)
    # The gap is larger than 15 minutes, so the meal event should be skipped
    assert len(events) == 0

def test_extract_meal_events_incomplete_window():
    # Only 60 minutes of data after meal
    df = pd.DataFrame({
        'Timestamp': pd.date_range('2026-01-01 08:00', periods=60, freq='1min'),
        'Dexcom GL': np.linspace(100, 120, 60),
        'Meal Type': ['Breakfast'] + [np.nan] * 59,
    })
    
    events = extract_meal_events(df, max_cgm_gap_minutes=15)
    assert len(events) == 0

def test_extract_meal_events_missing_middle():
    # 130 minutes of data, with a 5-minute missing block in the middle (which is < 15 min max gap)
    times = pd.date_range('2026-01-01 08:00', periods=130, freq='1min')
    cgm = np.linspace(100, 150, 130)
    # create a 5 minute gap of missing data starting at index 30 (08:30)
    cgm[30:35] = np.nan
    
    df = pd.DataFrame({
        'Timestamp': times,
        'Dexcom GL': cgm,
        'Meal Type': ['Breakfast'] + [np.nan] * 129,
        'Calories': [350] + [np.nan] * 129,
    })
    
    events = extract_meal_events(df, max_cgm_gap_minutes=15)
    assert len(events) == 1
    
    event = events[0]
    # The length of the window array should remain 121 (full span)
    assert len(event['CGM_Window']) == 121
    
    # Check that NaNs are preserved in the list output
    assert np.isnan(event['CGM_Window'][30:35]).all()
