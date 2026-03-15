import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to sys.path to import the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bambulab_metrics_exporter.cloud_auth import get_bind_devices, _get_json
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
    
    print(f"Verifying token and fetching devices for serial: {serial}...")
    
    api_bases = ["https://api.bambulab.com", "https://api-eu.bambulab.com"]
    
    for base in api_bases:
        print(f"\n--- Testing API Base: {base} ---")
        try:
            # Test profile
            print("Fetching profile...")
            profile = _get_json(base, "/v1/user-service/my/profile", 10, 0, token)
            print(f"Profile keys: {list(profile.keys())}")
            if "nickname" in profile:
                print(f"Nickname: {profile['nickname']}")
            
            # Test devices
            print("Fetching devices...")
            # Try different paths
            paths = ["/v1/user-service/my/bind/devices", "/v1/iot-service/api/user/bind"]
            for path in paths:
                print(f"  Trying path: {path}")
                try:
                    data = _get_json(base, path, 10, 0, token)
                    devices = data.get("devices", [])
                    print(f"  Success on {path}! Total devices: {len(devices)}")
                    
                    for dev in devices:
                        print(f"    - Device: {dev.get('name')} | Serial: {dev.get('dev_id')} | Model: {dev.get('model')}")
                        if dev.get('dev_id') == serial:
                            print("      >>> MATCH FOUND <<<")
                            print(json.dumps(dev, indent=2))
                    
                    if devices:
                        break # Found something
                except Exception as e:
                    print(f"  Failed on {path}: {e}")
        
        except Exception as e:
            print(f"Error on {base}: {e}")

if __name__ == "__main__":
    test_cloud_connection()
