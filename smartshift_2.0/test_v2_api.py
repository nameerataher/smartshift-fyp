"""
test_v2_api.py

quick test script for the new v2 api endpoints
run after starting api_server.py
"""

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:5000/api/v2"

def test_health():
    """test health check"""
    print("\n=== testing health check ===")
    response = requests.get(f"{BASE_URL}/health")
    print(f"status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

def test_comfort_score():
    """test comfort score calculation"""
    print("\n=== testing comfort score ===")
    data = {
        "shadow_ratio": 0.7,
        "heat_risk_score": 0.3
    }
    response = requests.post(f"{BASE_URL}/comfort-score", json=data)
    print(f"status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

def test_schedule():
    """test scheduling endpoint"""
    print("\n=== testing schedule optimization ===")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    data = {
        "task_name": "facade cleaning - south wall",
        "work_zone": {
            "zone_id": "burj_south",
            "name": "burj khalifa south facade",
            "lat": 25.197197,
            "lon": 55.274376,
            "radius": 25,
            "is_facade": True,
            "orientation": 180
        },
        "task_duration_minutes": 120,
        "date": tomorrow,
        "start_hour": 9,
        "end_hour": 17
    }
    
    response = requests.post(f"{BASE_URL}/schedule", json=data)
    print(f"status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        if result.get('success'):
            rec = result['recommendation']
            print(f"best time: {rec['best_schedule']['start_time']}")
            print(f"comfort score: {rec['best_schedule']['comfort_score']:.2f}")
            print(f"shadow: {rec['best_schedule']['shadow_percentage']:.0f}%")
            print(f"reason: {rec['recommendation_reason']}")
            print(f"alternatives: {len(rec['alternatives'])} options")
        else:
            print(f"error: {result.get('error')}")
    else:
        print(f"error: {response.text}")

def test_work_zones():
    """test work zone management"""
    print("\n=== testing work zones ===")
    
    # list zones
    response = requests.get(f"{BASE_URL}/work-zones")
    print(f"get status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    
    # create zone
    new_zone = {
        "zone_id": "test_construction",
        "name": "downtown construction site",
        "lat": 25.195,
        "lon": 55.275,
        "radius": 30,
        "zone_type": "construction"
    }
    
    response = requests.post(f"{BASE_URL}/work-zones", json=new_zone)
    print(f"\npost status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

def test_heatmap():
    """test heatmap generation"""
    print("\n=== testing heatmap ===")
    data = {
        "bbox": {
            "min_lat": 25.19,
            "max_lat": 25.21,
            "min_lon": 55.26,
            "max_lon": 55.28
        },
        "grid_size_meters": 50,
        "time": datetime.now().isoformat()
    }
    
    response = requests.post(f"{BASE_URL}/heatmap", json=data)
    print(f"status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        if result.get('success'):
            num_cells = len(result['geojson']['features'])
            print(f"generated {num_cells} grid cells")
            print(f"grid size: {result['metadata']['grid_size_meters']}m")
            # show first cell
            if num_cells > 0:
                first = result['geojson']['features'][0]
                props = first['properties']
                print(f"\nsample cell:")
                print(f"  comfort: {props['comfort_score']:.2f}")
                print(f"  shadow: {props['shadow_ratio']:.2f}")
                print(f"  heat risk: {props['heat_risk_score']:.2f}")
        else:
            print(f"error: {result.get('error')}")
    else:
        print(f"error: {response.text}")

def main():
    """run all tests"""
    print("=" * 60)
    print("smartshift 2.0 - v2 api tests")
    print("=" * 60)
    
    try:
        test_health()
        test_comfort_score()
        test_schedule()
        test_work_zones()
        test_heatmap()
        
        print("\n" + "=" * 60)
        print("✓ all tests completed")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n❌ error: could not connect to api server")
        print("make sure api_server.py is running:")
        print("  cd smartshift_2.0")
        print("  python api_server.py")
    except Exception as e:
        print(f"\n❌ error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

