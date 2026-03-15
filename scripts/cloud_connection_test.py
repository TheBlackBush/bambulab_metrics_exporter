import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to sys.path to import the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bambulab_metrics_exporter.cloud_auth import get_bind_devices
from bambulab_metrics_exporter.config import Settings

def test_cloud_connection():
    # Load .env explicitly
    load_dotenv(Path(__file__).parent.parent / ".env")
    
    settings = Settings()
    token = settings.bambulab_cloud_access_token
    serial = settings.bambulab_serial
    
    if not token:
        print("Error: BAMBULAB_CLOUD_ACCESS_TOKEN is missing")
        return
    
    print(f"Connecting to Cloud API with serial: {serial}...")
    
    try:
        devices = get_bind_devices(token)
        print(f"Total devices found in account: {len(devices)}")
        
        # Look for our specific device
        device = next((d for d in devices if d.get("dev_id") == serial), None)
        
        if device:
            print("\n--- Discovered Device Info ---")
            for key, value in device.items():
                print(f"{key}: {value}")
        else:
            print(f"\nError: Device with serial {serial} not found in account.")
            if devices:
                print("\nAvailable serials in account:")
                for d in devices:
                    print(f"- {d.get('dev_id')} ({d.get('name')})")
                    
    except Exception as e:
        print(f"Error during cloud connection: {e}")

if __name__ == "__main__":
    test_cloud_connection()
