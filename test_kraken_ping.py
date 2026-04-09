# test_kraken_ping.py
import requests, time

print("Testing Kraken connection...")
for i in range(3):
    try:
        start = time.time()
        r = requests.get(
            "https://api.kraken.com/0/public/Time",
            timeout=60
        )
        elapsed = time.time() - start
        print(f"Attempt {i+1}: ✅ {r.status_code} | {elapsed:.1f}s")
        print(f"Response: {r.json()}")
        break
    except Exception as e:
        print(f"Attempt {i+1}: ❌ {e}")
        time.sleep(5)