# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pandas",
#     "pyarrow",
# ]
# ///

import queue
import threading
import pandas as pd
import time
from collections import deque
import pyarrow as pa
import pyarrow.parquet as pq
import json

CSV_FILE = "realKnownCause/machine_temperature_system_failure.csv"
OUTPUT_PARQUET = "features.parquet"

class Producer(threading.Thread):
    def __init__(self, q, csv_path):
        super().__init__()
        self.q = q
        self.csv_path = csv_path
        
    def run(self):
        print(f"[Producer] Reading data from {self.csv_path}...")
        try:
            df = pd.read_csv(self.csv_path)
            for _, row in df.iterrows():
                # Emit each row as a dict
                event = row.to_dict()
                self.q.put(event)
        except Exception as e:
            print(f"[Producer] Error: {e}")
        finally:
            print("[Producer] Finished emitting data.")
            self.q.put(None) # Sentinel value to signal end of stream

class Consumer(threading.Thread):
    def __init__(self, q):
        super().__init__()
        self.q = q
        self.window = deque(maxlen=12) # 1 hour window at 5-min intervals
        self.results = []
        
    def run(self):
        print("[Consumer] Starting feature extraction stream...")
        count = 0
        while True:
            event = self.q.get()
            if event is None:
                self.q.task_done()
                break
                
            value = event['value']
            self.window.append(value)
            
            # Extract features (rolling mean, rolling std, rate of change)
            if len(self.window) > 1:
                rolling_mean = sum(self.window) / len(self.window)
                rolling_std = pd.Series(self.window).std()
                rate_of_change = (self.window[-1] - self.window[-2]) / self.window[-2] if self.window[-2] != 0 else 0
            else:
                rolling_mean = value
                rolling_std = 0.0
                rate_of_change = 0.0
                
            feature_event = {
                'timestamp': event['timestamp'],
                'value': value,
                'rolling_mean_1h': rolling_mean,
                'rolling_std_1h': rolling_std,
                'rate_of_change': rate_of_change
            }
            self.results.append(feature_event)
            count += 1
            
            if count % 5000 == 0:
                print(f"[Consumer] Processed {count} events...")
                
            self.q.task_done()
            
        print(f"[Consumer] Finished processing. Total events: {len(self.results)}")
        
        # Output to Parquet
        print(f"[Consumer] Writing features to {OUTPUT_PARQUET}...")
        out_df = pd.DataFrame(self.results)
        out_df.to_parquet(OUTPUT_PARQUET, engine='pyarrow')
        print("[Consumer] Pipeline complete.")

if __name__ == "__main__":
    event_queue = queue.Queue(maxsize=10000)
    
    producer = Producer(event_queue, CSV_FILE)
    consumer = Consumer(event_queue)
    
    start_time = time.time()
    
    consumer.start()
    producer.start()
    
    producer.join()
    consumer.join()
    
    print(f"Total pipeline execution time: {time.time() - start_time:.2f} seconds")
