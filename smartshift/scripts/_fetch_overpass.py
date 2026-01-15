import requests, json

bbox = (55.25090, 25.17069, 55.29405, 25.20328)

query = "[out:json][timeout:180];(" \
        + f"way[\"building\"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});" \
        + f"relation[\"building\"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});" \
        + ");out body geom;"

r = requests.post("https://overpass-api.de/api/interpreter", data=query)
r.raise_for_status()
data = r.json()

out_path = r"C:\Users\hp\Downloads\nxt309\dubai_overpass.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f)

print("Saved", out_path, "elements:", len(data.get("elements", [])))
