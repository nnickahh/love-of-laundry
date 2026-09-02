"""
verify_system.py
Integration test script for the Garment Inspection & Tracking System.
Simulates both local Edge RPi scans and Cloud syncing flow.

Steps to test manually:
  1. Open a PowerShell terminal and start the Cloud Server:
     .venv\\Scripts\\python -m uvicorn cloud.main:app --port 8080 --reload
     
  2. Open a second PowerShell terminal and start the Edge Local Server:
     set DEVICE_ID=Van-01
     set CLOUD_URL=http://localhost:8080
      set CAMERA_SOURCE=assets/test_clothing.png
     .venv\\Scripts\\python -m uvicorn edge.main:app --port 8000 --reload
     
  3. Open your browser:
     - Operator UI (Edge):  http://localhost:8000/static/index.html
     - Admin Dashboard (Cloud): http://localhost:8080/static/dashboard.html
     
  4. Trigger a scan in the Operator UI. Check that the item syncs to the Cloud dashboard!
"""

import os
import sys
import time
import httpx
import subprocess
from pathlib import Path

def test_integration():
    print("=" * 60)
    print("  Garment Inspection System — Integration Test")
    print("=" * 60)
    
    # Check if uvicorn is installed
    try:
        import uvicorn
    except ImportError:
        print("Uvicorn is not installed in the environment. Please run: pip install uvicorn")
        return
        
    print("1. Starting Cloud Server on port 8080...")
    cloud_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cloud.main:app", "--port", "8080"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    print("2. Starting Edge Server on port 8000...")
    # Configure environment variables for edge server testing
    env = os.environ.copy()
    env["DEVICE_ID"] = "Test-Van-99"
    env["CLOUD_URL"] = "http://localhost:8080"
    env["CAMERA_SOURCE"] = "assets/test_clothing.png"
    
    edge_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "edge.main:app", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True
    )
    
    # Wait for servers to spin up
    print("Waiting up to 20 seconds for servers to initialize and spin up...")
    for i in range(20):
        try:
            with httpx.Client(timeout=1.0) as cl:
                r1 = cl.get("http://localhost:8080/api/reports")
                r2 = cl.get("http://localhost:8000/api/status")
                if r1.status_code == 200 and r2.status_code == 200:
                    print("   Both servers are online and responsive!")
                    break
        except Exception:
            pass
        time.sleep(1.0)
    else:
        print("   Warning: Servers did not respond within 20 seconds. Proceeding anyway...")

    
    client = httpx.Client(timeout=30.0)
    
    try:
        # Check cloud server status
        print("\n3. Testing Cloud Server availability...")
        cloud_resp = client.get("http://localhost:8080/api/reports")
        print(f"   Cloud status code: {cloud_resp.status_code}")
        print(f"   Cloud report stats: {cloud_resp.json()}")
        
        # Check edge status
        print("\n4. Testing Edge Server availability...")
        edge_resp = client.get("http://localhost:8000/api/status")
        print(f"   Edge status code: {edge_resp.status_code}")
        print(f"   Edge status data: {edge_resp.json()}")
        
        # Trigger mock scan on edge
        print("\n5. Triggering a garment scan on Edge...")
        scan_resp = client.post("http://localhost:8000/api/scan")
        if scan_resp.status_code == 200:
            scan_data = scan_resp.json()
            print(f"   Scan successful! Local ID: {scan_data['local_id']}")
            print(f"   Detected garment: {scan_data['garment_type']} | Status: {scan_data['status']}")
            print(f"   Defects found: {len(scan_data['defects'])}")
            
            # Confirm scan
            print("\n6. Confirming scan as operator...")
            confirm_resp = client.post("http://localhost:8000/api/confirm", json={
                "local_id": scan_data["local_id"],
                "garment_type": scan_data["garment_type"],
                "status": scan_data["status"]
            })
            print(f"   Confirm status code: {confirm_resp.status_code}")
            
            # Wait for background sync thread to run (polls every 10 sec)
            print("\n7. Waiting 12 seconds for background sync thread to upload item to Cloud...")
            time.sleep(12)
            
            # Check Cloud DB for synced item
            print("\n8. Checking Central Cloud Database for synced garments...")
            garments_resp = client.get("http://localhost:8080/api/garments")
            garments = garments_resp.json()
            
            synced_item = None
            for g in garments:
                if g["device_id"] == "Test-Van-99" and g["local_id"] == scan_data["local_id"]:
                    synced_item = g
                    break
                    
            if synced_item:
                print("   SUCCESS! Synced item found in Cloud DB.")
                print(f"   Central Cloud ID: {synced_item['garment_id']}")
                print(f"   Central Image URL: {synced_item['image_url']}")
                print(f"   Defects registered: {[d['label'] for d in synced_item['defects']]}")
            else:
                print("   FAILED: Synced item not found in Cloud Database.")
        else:
            print(f"   Scan trigger failed with status: {scan_resp.status_code}")
            
    except Exception as e:
        print(f"\nError occurred during integration test: {e}")
        
    finally:
        # Clean up processes
        print("\n9. Shutting down Edge and Cloud servers...")
        edge_proc.terminate()
        cloud_proc.terminate()
        edge_proc.wait()
        cloud_proc.wait()
        print("   Shutdown complete.")
        print("=" * 60)

if __name__ == "__main__":
    test_integration()
