from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from bambulab_metrics_exporter import cloud_auth


def test_cloud_auth_updates_env_file_with_model_and_name(tmp_path: Path) -> None:
    # 1. Setup mock environment and data
    env_file = tmp_path / "test.env"
    env_file.write_text("BAMBULAB_SERIAL=S123\n")
    
    mock_result = MagicMock()
    mock_result.access_token = "fake-access-token"
    mock_result.user_id = "fake-user-id"
    mock_result.refresh_token = "fake-refresh-token"
    
    mock_devices = [
        {"dev_id": "S123", "name": "MyP1S", "model": "P1S"}
    ]
    
    # 2. Mock all external dependencies
    with patch("bambulab_metrics_exporter.cloud_auth.login_with_code", return_value=mock_result), \
         patch("bambulab_metrics_exporter.cloud_auth._get_bind_devices", return_value=mock_devices), \
         patch("sys.stdout"), \
         patch("argparse.ArgumentParser.parse_args") as mock_args:
        
        mock_args.return_value = MagicMock(
            email="test@test.com",
            code="123456",
            send_code=False,
            serial="S123",
            save=False,
            env_file=str(env_file),
            config_dir="/tmp",
            credentials_file="creds.json",
            secret_key="",
            timeout=10,
            retries=0,
            api_bases="https://api.fake.com"
        )
        
        # 3. Run the script logic
        cloud_auth.main()
        
    # 4. Verify the file content
    content = env_file.read_text()
    print(f"DEBUG: File content after sync:\n{content}")
    
    assert "BAMBULAB_PRINTER_NAME=MyP1S" in content
    assert "BAMBULAB_PRINTER_MODEL=P1S" in content
    assert "BAMBULAB_CLOUD_ACCESS_TOKEN=fake-access-token" in content

if __name__ == "__main__":
    # If run directly, we'll use a temp dir
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_cloud_auth_updates_env_file_with_model_and_name(Path(td))
        print("\nVerification successful!")
