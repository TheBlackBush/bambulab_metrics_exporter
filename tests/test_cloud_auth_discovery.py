import os
import json
from unittest.mock import patch, MagicMock
from bambulab_metrics_exporter import cloud_auth

def test_get_bind_devices_success():
    mock_data = {
        "devices": [
            {"dev_id": "S1", "name": "P1S-Living", "model": "P1S"},
            {"dev_id": "S2", "name": "X1C-Work", "model": "X1C"}
        ]
    }
    
    with patch("bambulab_metrics_exporter.cloud_auth._get_json", return_value=mock_data):
        devices = cloud_auth.get_bind_devices("tok", 10, 1, ["base"])
        assert len(devices) == 2
        assert devices[0]["dev_id"] == "S1"

def test_cloud_auth_main_discovers_name_model():
    mock_result = MagicMock()
    mock_result.access_token = "tok"
    mock_result.user_id = "uid"
    mock_result.refresh_token = "ref"
    
    mock_devices = [
        {"dev_id": "S123", "name": "MyPrinter", "model": "P1S"}
    ]
    
    with patch("bambulab_metrics_exporter.cloud_auth.login_with_code", return_value=mock_result):
        with patch("bambulab_metrics_exporter.cloud_auth.get_bind_devices", return_value=mock_devices):
            with patch("bambulab_metrics_exporter.cloud_auth.sync_env_file"):
                with patch("sys.stdout"): # Mute prints
                    # Setup args
                    with patch("argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            email="a@b.com", code="123", send_code=False, 
                            serial="S123", save=False, env_file=".env",
                            timeout=10, retries=1, api_bases="base",
                            config_dir="/config", credentials_file="cred.json",
                            secret_key=""
                        )
                        cloud_auth.main()
                        
                        assert os.environ.get("BAMBULAB_PRINTER_NAME") == "MyPrinter"
                        assert os.environ.get("BAMBULAB_PRINTER_MODEL") == "P1S"
