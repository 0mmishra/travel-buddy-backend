from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from openai import OpenAI
from dotenv import load_dotenv

# -------------------- Load Environment Variables --------------------
load_dotenv()

app = Flask(__name__)
CORS(app)

# Get API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
OPENTRIPMAP_API_KEY = os.getenv("OPENTRIPMAP_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY not found in .env file")
if not WEATHER_API_KEY:
    raise ValueError("❌ WEATHER_API_KEY not found in .env file")
if not OPENTRIPMAP_API_KEY:
    raise ValueError("❌ OPENTRIPMAP_API_KEY not found in .env file")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------- System Prompt --------------------
system_prompt = """
You are a helpful AI travel buddy.
Answer concisely in short bullet points only.
Do NOT write long paragraphs or extra descriptions.
Do NOT use markdown, headings, or bold.
Follow this exact format:

Day 1:
- Morning: ...
- Afternoon: ...
- Evening: ...

Day 2:
- Morning: ...
- Afternoon: ...
- Evening: ...

Day 3:
- Morning: ...
- Afternoon: ...
- Evening: ...

Tips:
- Tip 1
- Tip 2

Keep all sentences to one line max. Only provide essential info for each time slot. No extra text.
"""

# -------------------- Chat Endpoint --------------------
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_input = request.json.get("message")

        # Handle greetings separately
        if user_input and user_input.lower() in ["hi", "hello", "hey"]:
            return jsonify({
                "reply": "Hello! I can help you plan trips. Where would you like to go?",
                "city": None
            })

        # Call OpenAI API for trip plan
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7
        )
        reply = completion.choices[0].message.content

        # --- City detection using OpenAI ---
        city = None
        try:
            city_completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Extract only the main city name from this query. Reply with just the city, nothing else."},
                    {"role": "user", "content": user_input}
                ],
                temperature=0
            )
            city = city_completion.choices[0].message.content.strip()
        except Exception as e:
            print("OpenAI city extraction error:", str(e))

        # --- Fallback: use Nominatim if OpenAI didn’t detect ---
        if not city:
            try:
                geo_url = f"https://nominatim.openstreetmap.org/search?format=json&q={user_input}"
                geo_res = requests.get(geo_url, headers={"User-Agent": "travel-buddy"}).json()
                if geo_res:
                    display_name = geo_res[0].get("display_name", "")
                    city = display_name.split(",")[0] if display_name else None
            except Exception as e:
                print("Fallback city detection error:", str(e))

        return jsonify({"reply": reply, "city": city})

    except Exception as e:
        print("ERROR in /chat:", str(e))
        return jsonify({"error": str(e)}), 500


# -------------------- Weather Endpoint --------------------
@app.route("/weather", methods=["GET"])
def weather():
    city = request.args.get("city")
    if not city:
        return jsonify({"error": "City is required"}), 400

    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        res = requests.get(url)
        data = res.json()

        if res.status_code != 200 or "main" not in data:
            return jsonify({"error": "Weather not found"}), 404

        return jsonify({
            "temperature": data["main"]["temp"],
            "condition": data["weather"][0]["description"],
            "city": data.get("name", city)
        })
    except Exception as e:
        print("ERROR in /weather:", str(e))
        return jsonify({"error": str(e)}), 500


# -------------------- Hotels Endpoint --------------------
@app.route("/hotels", methods=["GET"])
def hotels():
    city = request.args.get("city")
    if not city:
        return jsonify({"error": "City is required"}), 400

    try:
        # Step 1: Get coordinates from Nominatim
        nominatim_url = f"https://nominatim.openstreetmap.org/search?format=json&q={city}"
        nom_res = requests.get(nominatim_url, headers={"User-Agent": "travel-buddy"}).json()

        if not nom_res:
            return jsonify({"error": "City not found"}), 404

        lat, lon = nom_res[0]["lat"], nom_res[0]["lon"]

        # Step 2: Fetch hotels using OpenTripMap (LIMIT = 5)
        places_url = (
            f"https://api.opentripmap.com/0.1/en/places/radius?"
            f"radius=5000&lon={lon}&lat={lat}&kinds=accomodations&limit=5&apikey={OPENTRIPMAP_API_KEY}"
        )
        places_res = requests.get(places_url).json()

        hotels_list = []
        for place in places_res.get("features", []):
            props = place["properties"]
            coords = place["geometry"]["coordinates"]
            hotel_name = props.get("name", "Unnamed")

            if not hotel_name:
                continue

            # Generate booking & maps links
            booking_link = f"https://www.booking.com/searchresults.html?ss={hotel_name}+{city}"
            google_maps_link = f"https://www.google.com/maps/search/{hotel_name}+{city}"

            hotels_list.append({
                "name": hotel_name,
                "lat": coords[1],
                "lon": coords[0],
                "map_link": f"https://www.openstreetmap.org/?mlat={coords[1]}&mlon={coords[0]}#map=18/{coords[1]}/{coords[0]}",
                "booking_link": booking_link,
                "google_maps_link": google_maps_link
            })

        return jsonify(hotels_list)
    except Exception as e:
        print("ERROR in /hotels:", str(e))
        return jsonify({"error": str(e)}), 500



# -------------------- Geocode Endpoint --------------------
@app.route("/geocode", methods=["GET"])
def geocode():
    place = request.args.get("place")
    if not place:
        return jsonify({"error": "Place is required"}), 400

    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={place}"
        res = requests.get(url, headers={"User-Agent": "travel-buddy"}).json()

        if res:
            return jsonify({
                "name": res[0].get("display_name", place),
                "lat": res[0]["lat"],
                "lon": res[0]["lon"]
            })

        return jsonify({"error": "No results found"}), 404
    except Exception as e:
        print("ERROR in /geocode:", str(e))
        return jsonify({"error": str(e)}), 500


# -------------------- Main --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
