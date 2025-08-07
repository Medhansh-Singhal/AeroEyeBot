import requests
import time
import json
import math
import telebot
from datetime import datetime, timedelta
import logging
import threading
import sqlite3
from telebot import types
import os

class AeroEyeBot:
    def __init__(self, telegram_bot_token):
        # Telegram bot setup
        self.bot = telebot.TeleBot(telegram_bot_token)
        
        # OpenSky Network API (free)
        self.opensky_base_url = "https://opensky-network.org/api/states/all"
        
        # Database for user monitoring areas
        self.init_database()
        
        # Active monitoring areas
        self.monitoring_areas = {}
        self.notified_flights = {}
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Setup bot commands
        self.setup_commands()
        
    def init_database(self):
        """Initialize SQLite database for user data"""
        self.conn = sqlite3.connect('aeroeyebot.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitoring_areas (
                chat_id INTEGER PRIMARY KEY,
                area_name TEXT,
                north_lat REAL,
                south_lat REAL,
                east_lon REAL,
                west_lon REAL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flight_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                flight_icao TEXT,
                notification_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def setup_commands(self):
        """Setup bot command handlers"""
        
        @self.bot.message_handler(commands=['start'])
        def start_command(message):
            self.send_welcome(message)
            
        @self.bot.message_handler(commands=['help'])
        def help_command(message):
            self.send_help(message)
            
        @self.bot.message_handler(commands=['setarea'])
        def setarea_command(message):
            self.request_area_setup(message)
            
        @self.bot.message_handler(commands=['myarea'])
        def myarea_command(message):
            self.show_current_area(message)
            
        @self.bot.message_handler(commands=['start_monitoring'])
        def start_monitoring_command(message):
            self.start_user_monitoring(message)
            
        @self.bot.message_handler(commands=['stop_monitoring'])
        def stop_monitoring_command(message):
            self.stop_user_monitoring(message)
            
        @self.bot.message_handler(commands=['precision_helper'])
        def precision_helper_command(message):
            self.send_precision_helper(message)
            
        @self.bot.message_handler(commands=['status'])
        def status_command(message):
            self.show_status(message)
            
        # Handle coordinate input
        @self.bot.message_handler(func=lambda message: self.is_coordinate_message(message))
        def handle_coordinates(message):
            self.process_coordinates(message)
            
    def send_welcome(self, message):
        """Send welcome message with instructions"""
        welcome_text = """🛩️ Welcome to AeroEyeBot!

I can track flights over any area you specify and notify you when aircraft pass overhead.

🚀 **Quick Start:**
1. Use /setarea to define your monitoring area
2. Use /start_monitoring to begin tracking
3. Get notified when flights pass over your area!

📍 **How to set your area:**
Send me 4 coordinates in this format:
`North_Lat, South_Lat, East_Lon, West_Lon`

Example for Jaipur:
`26.95, 26.87, 75.82, 75.74`

📋 **Commands:**
/help - Show all commands
/setarea - Set monitoring area
/myarea - Show current area
/start_monitoring - Start flight tracking
/stop_monitoring - Stop flight tracking  
/status - Check bot status

Ready to track some flights? ✈️"""
        
        self.bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown')
    
    def send_precision_helper(self, message):
        """Help users create precise monitoring areas"""
        helper_text = """🎯 **Precision Area Calculator**

To create ultra-precise monitoring areas (500m-1000m), follow these steps:

**Step 1: Get Your Exact Location**
1. Open Google Maps
2. Find your exact position
3. Right-click and copy coordinates
4. Example: `26.9124, 75.7873`

**Step 2: Choose Your Precision Level**

📐 **For 500m radius (1km²):**
Add/subtract these values from your coordinates:
• Latitude: ±0.0045°  
• Longitude: ±0.005°

📐 **For 1000m radius (4km²):**  
Add/subtract these values:
• Latitude: ±0.009°
• Longitude: ±0.01°

**Step 3: Calculate Your Boundaries**

**Example calculation for 1000m radius:**
Your location: `26.9124, 75.7873`

```
North = 26.9124 + 0.009 = 26.9214
South = 26.9124 - 0.009 = 26.9034  
East  = 75.7873 + 0.01  = 75.7973
West  = 75.7873 - 0.01  = 75.7773
```

**Send to bot:**
`26.9214, 26.9034, 75.7973, 75.7773`

**Why Ultra-Precise?**
✅ Detect only flights directly overhead
✅ Reduce false positives  
✅ Perfect for residential monitoring
✅ Ideal for aviation spotting

Need help with calculation? Send your center coordinates and desired radius! 🤖"""
        
        self.bot.send_message(message.chat.id, helper_text, parse_mode='Markdown')
    
    def send_help(self, message):
        """Send help message"""
        help_text = """🆘 **AeroEyeBot Help**

**Setting Up Your Area:**
1. Use /setarea command
2. Send coordinates: `North, South, East, West`
3. Example: `26.95, 26.87, 75.82, 75.74`

**Coordinate Tips:**
📍 Use Google Maps to find coordinates
📍 North > South (latitude)  
📍 East > West (longitude for most locations)
📍 Larger area = more flights detected
📍 Smaller area = more precise "overhead" detection

**Commands:**
/setarea - Set new monitoring area
/precision_helper - Calculate precise coordinates
/myarea - View your current area
/start_monitoring - Begin flight tracking
/stop_monitoring - Stop notifications
/status - Bot and area status

**Area Examples:**
🏠 **Small area (5km radius):**
Around your house: precise overhead detection

🏙️ **Medium area (city-wide):**
Cover entire city: catch more flights

🌍 **Large area (regional):**
Cover multiple cities: maximum coverage

**Need coordinates?**
1. Open Google Maps
2. Right-click on location
3. Copy the coordinates
4. Use format: North, South, East, West

Questions? Just ask! 🤖"""
        
        self.bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
    
    def request_area_setup(self, message):
        """Request area setup from user"""
        setup_text = """📍 **Set Your Monitoring Area**

Please send me 4 coordinates in this format:
`North_Lat, South_Lat, East_Lon, West_Lon`

**Examples by Area Size:**

🎯 **Ultra-Precise (500m radius):**
`26.9169, 26.9079, 75.7923, 75.7823`
*Perfect for: House/building level tracking*

🏠 **Precise (1km radius):**
`26.9214, 26.9034, 75.7973, 75.7773`
*Perfect for: Neighborhood tracking*

🏘️ **Small Area (5km radius):**
`26.95, 26.87, 75.82, 75.74`
*Perfect for: Local area tracking*

🏙️ **City-wide (25km radius):**  
`28.9, 28.4, 77.4, 76.8`
*Perfect for: Entire city tracking*

**Quick Setup Helper:**
Use /precision_helper to calculate precise coordinates from your location!

**How to get coordinates:**
1. Open Google Maps
2. Find your exact location  
3. Use our precision calculator below
4. Send coordinates in the format above

Send your coordinates now! 📡"""
        
        self.bot.send_message(message.chat.id, setup_text, parse_mode='Markdown')
    
    def is_coordinate_message(self, message):
        """Check if message contains coordinates"""
        try:
            coords = message.text.strip().replace(' ', '').split(',')
            return len(coords) == 4 and all(self.is_float(coord) for coord in coords)
        except:
            return False
    
    def is_float(self, value):
        """Check if string can be converted to float"""
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    def process_coordinates(self, message):
        """Process coordinate input from user"""
        try:
            coords = [float(x.strip()) for x in message.text.strip().split(',')]
            north_lat, south_lat, east_lon, west_lon = coords
            
            # Validate coordinates
            if not self.validate_coordinates(north_lat, south_lat, east_lon, west_lon):
                error_msg = """❌ **Invalid Coordinates**

Please check:
• North latitude > South latitude
• Coordinates within valid range (-90 to 90 for lat, -180 to 180 for lon)
• All 4 values provided

Try again with format: `North, South, East, West`"""
                self.bot.send_message(message.chat.id, error_msg, parse_mode='Markdown')
                return
            
            # Save to database
            self.save_user_area(message.chat.id, north_lat, south_lat, east_lon, west_lon)
            
            # Calculate area info
            area_info = self.calculate_area_info(north_lat, south_lat, east_lon, west_lon)
            
            success_msg = f"""✅ **Area Set Successfully!**

📍 **Your Monitoring Area:**
🧭 North: {north_lat}°
🧭 South: {south_lat}°  
🧭 East: {east_lon}°
🧭 West: {west_lon}°

📏 **Area Details:**
📐 Width: ~{area_info['width_km']:.1f} km
📐 Height: ~{area_info['height_km']:.1f} km  
📊 Total Area: ~{area_info['area_km2']:.0f} km²

🚀 **Ready to start!**
Use /start_monitoring to begin flight tracking.

The bot will notify you whenever aircraft fly through this area! ✈️"""
            
            self.bot.send_message(message.chat.id, success_msg, parse_mode='Markdown')
            
        except Exception as e:
            self.logger.error(f"Error processing coordinates: {e}")
            self.bot.send_message(message.chat.id, "❌ Error processing coordinates. Please try again with format: North, South, East, West")
    
    def validate_coordinates(self, north, south, east, west):
        """Validate coordinate values"""
        # Basic range validation
        if not (-90 <= north <= 90 and -90 <= south <= 90):
            return False
        if not (-180 <= east <= 180 and -180 <= west <= 180):
            return False
        
        # Logical validation
        if north <= south:
            return False
        
        # For longitude, handle cases where area crosses 180/-180 line
        # For simplicity, assume west < east for now
        if west >= east:
            return False
            
        return True
    
    def save_user_area(self, chat_id, north, south, east, west):
        """Save user monitoring area to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO monitoring_areas 
            (chat_id, north_lat, south_lat, east_lon, west_lon, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (chat_id, north, south, east, west))
        self.conn.commit()
    
    def calculate_area_info(self, north, south, east, west):
        """Calculate area dimensions"""
        # Approximate calculations
        lat_diff = north - south
        lon_diff = east - west
        
        # Convert to km (rough approximation)
        height_km = lat_diff * 111  # 1 degree lat ≈ 111 km
        width_km = lon_diff * 111 * math.cos(math.radians((north + south) / 2))
        area_km2 = height_km * width_km
        
        return {
            'width_km': abs(width_km),
            'height_km': abs(height_km),
            'area_km2': abs(area_km2)
        }
    
    def show_current_area(self, message):
        """Show user's current monitoring area"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM monitoring_areas WHERE chat_id = ?', (message.chat.id,))
        area = cursor.fetchone()
        
        if not area:
            no_area_msg = """📍 **No Area Set**

You haven't set a monitoring area yet.

Use /setarea to define your area, then send coordinates like:
`26.95, 26.87, 75.82, 75.74`

Need help? Use /help for detailed instructions! 🤖"""
            self.bot.send_message(message.chat.id, no_area_msg, parse_mode='Markdown')
            return
        
        chat_id, area_name, north, south, east, west, is_active, created = area
        area_info = self.calculate_area_info(north, south, east, west)
        
        status = "🟢 Active" if is_active else "🔴 Inactive"
        monitoring_status = "🟢 Monitoring" if chat_id in self.monitoring_areas else "🔴 Stopped"
        
        area_msg = f"""📍 **Your Monitoring Area**

🧭 **Coordinates:**
• North: {north}°
• South: {south}°  
• East: {east}°
• West: {west}°

📏 **Dimensions:**
• Width: ~{area_info['width_km']:.1f} km
• Height: ~{area_info['height_km']:.1f} km
• Area: ~{area_info['area_km2']:.0f} km²

📊 **Status:**
• Area: {status}
• Monitoring: {monitoring_status}
• Created: {created}

🚀 **Actions:**
• /start_monitoring - Start tracking
• /stop_monitoring - Stop tracking
• /setarea - Change area"""
        
        self.bot.send_message(message.chat.id, area_msg, parse_mode='Markdown')
    
    def start_user_monitoring(self, message):
        """Start monitoring for a user"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM monitoring_areas WHERE chat_id = ? AND is_active = 1', (message.chat.id,))
        area = cursor.fetchone()
        
        if not area:
            self.bot.send_message(message.chat.id, "❌ Please set your monitoring area first using /setarea")
            return
        
        chat_id, area_name, north, south, east, west, is_active, created = area
        
        # Add to active monitoring
        self.monitoring_areas[chat_id] = {
            'north': north,
            'south': south,
            'east': east,
            'west': west,
            'chat_id': chat_id
        }
        
        start_msg = f"""🚀 **Monitoring Started!**

✅ AeroEyeBot is now tracking flights over your area

📍 **Monitoring Zone:**
🧭 {north}°N to {south}°N
🧭 {west}°E to {east}°E

📡 **What to expect:**
• Real-time flight notifications
• Flight details (callsign, altitude, speed)
• Updates every 3 minutes
• Distance from your area center

🔕 **To stop:** Use /stop_monitoring

Happy flight tracking! ✈️📡"""
        
        self.bot.send_message(message.chat.id, start_msg, parse_mode='Markdown')
        self.logger.info(f"Started monitoring for chat_id: {chat_id}")
    
    def stop_user_monitoring(self, message):
        """Stop monitoring for a user"""
        chat_id = message.chat.id
        
        if chat_id in self.monitoring_areas:
            del self.monitoring_areas[chat_id]
            stop_msg = """🛑 **Monitoring Stopped**

Flight tracking has been disabled for your area.

🚀 **To restart:** Use /start_monitoring anytime

Thanks for using AeroEyeBot! ✈️"""
            self.bot.send_message(chat_id, stop_msg, parse_mode='Markdown')
            self.logger.info(f"Stopped monitoring for chat_id: {chat_id}")
        else:
            self.bot.send_message(chat_id, "ℹ️ Monitoring is not currently active for your area.")
    
    def show_status(self, message):
        """Show bot status"""
        active_users = len(self.monitoring_areas)
        
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM monitoring_areas WHERE is_active = 1')
        total_areas = cursor.fetchone()[0]
        
        status_msg = f"""📊 **AeroEyeBot Status**

🤖 **Bot Health:** ✅ Online
📡 **Data Source:** OpenSky Network
🔄 **Update Interval:** 3 minutes

👥 **Usage Stats:**
• Active Monitors: {active_users}
• Total Areas Set: {total_areas}
• Your Status: {'🟢 Monitoring' if message.chat.id in self.monitoring_areas else '🔴 Stopped'}

🌐 **Coverage:** Worldwide flight tracking
📱 **Platform:** Telegram Bot

Last Update: {datetime.now().strftime('%H:%M:%S')}"""
        
        self.bot.send_message(message.chat.id, status_msg, parse_mode='Markdown')
    
    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points"""
        R = 6371
        lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
        delta_lat, delta_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
    
    def get_flights_in_area(self, area):
        """Get flights in specific area"""
        try:
            params = {
                'lamin': area['south'],
                'lamax': area['north'],
                'lomin': area['west'], 
                'lomax': area['east']
            }
            
            response = requests.get(self.opensky_base_url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('states', []) if data else []
            else:
                self.logger.error(f"API Error: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"Error fetching flights: {e}")
            return []
    
    def is_flight_in_area(self, flight_state, area):
        """Check if flight is within monitoring area"""
        try:
            if len(flight_state) < 7:
                return False
            
            longitude = flight_state[5]
            latitude = flight_state[6] 
            on_ground = flight_state[8]
            
            if not longitude or not latitude or on_ground:
                return False
            
            # Check if within bounding box
            return (area['south'] <= latitude <= area['north'] and 
                   area['west'] <= longitude <= area['east'])
            
        except Exception as e:
            return False
    
    def format_flight_notification(self, flight_state, area):
        """Format flight notification message"""
        try:
            icao24 = flight_state[0] or "Unknown"
            callsign = flight_state[1] or "Unknown" 
            origin_country = flight_state[2] or "Unknown"
            longitude = flight_state[5] or 0
            latitude = flight_state[6] or 0
            baro_altitude = flight_state[7]
            velocity = flight_state[9]
            true_track = flight_state[10]
            vertical_rate = flight_state[11]
            
            # Calculate distance to area center
            center_lat = (area['north'] + area['south']) / 2
            center_lon = (area['east'] + area['west']) / 2  
            distance = round(self.haversine_distance(center_lat, center_lon, latitude, longitude), 2)
            
            altitude_ft = int(baro_altitude * 3.28084) if baro_altitude else "Unknown"
            speed_kmh = int(velocity * 3.6) if velocity else "Unknown"
            heading = int(true_track) if true_track else "Unknown"
            
            climb_status = ""
            if vertical_rate:
                if vertical_rate > 1:
                    climb_status = "📈 Climbing"
                elif vertical_rate < -1: 
                    climb_status = "📉 Descending"
                else:
                    climb_status = "➡️ Level Flight"
            
            message = f"""✈️ **FLIGHT IN YOUR AREA!**

🛩️ **Flight:** {callsign.strip()}
🆔 **Aircraft:** {icao24}
🌍 **Origin:** {origin_country}
📍 **Position:** {latitude:.4f}°, {longitude:.4f}°

📊 **Flight Data:**  
🏔️ Altitude: {altitude_ft} ft
🚀 Speed: {speed_kmh} km/h
🧭 Heading: {heading}°
📈 Status: {climb_status}

📏 **Distance:** {distance} km from area center
🕐 **Time:** {datetime.now().strftime('%H:%M:%S')}

Tracked by AeroEyeBot 🤖✈️"""
            
            return message
            
        except Exception as e:
            self.logger.error(f"Error formatting notification: {e}")
            return f"✈️ Flight detected in your area at {datetime.now().strftime('%H:%M:%S')}"
    
    def monitor_flights(self):
        """Main monitoring loop"""
        self.logger.info("Starting flight monitoring loop")
        
        while True:
            try:
                if not self.monitoring_areas:
                    time.sleep(60)
                    continue
                
                for chat_id, area in list(self.monitoring_areas.items()):
                    try:
                        flights = self.get_flights_in_area(area)
                        
                        for flight_state in flights:
                            if self.is_flight_in_area(flight_state, area):
                                icao24 = flight_state[0] or "unknown"
                                notification_key = f"{chat_id}_{icao24}"
                                
                                # Avoid spam (30 min cooldown per flight)
                                if notification_key in self.notified_flights:
                                    time_diff = (datetime.now() - self.notified_flights[notification_key]).seconds
                                    if time_diff < 1800:
                                        continue
                                
                                # Send notification
                                message = self.format_flight_notification(flight_state, area)
                                try:
                                    self.bot.send_message(chat_id, message, parse_mode='Markdown')
                                    self.notified_flights[notification_key] = datetime.now()
                                    self.logger.info(f"Sent notification to {chat_id} for flight {icao24}")
                                except Exception as e:
                                    self.logger.error(f"Failed to send notification to {chat_id}: {e}")
                    
                    except Exception as e:
                        self.logger.error(f"Error monitoring area for {chat_id}: {e}")
                
                # Cleanup old notifications
                current_time = datetime.now()
                self.notified_flights = {
                    key: timestamp for key, timestamp in self.notified_flights.items()
                    if (current_time - timestamp).seconds < 3600
                }
                
                time.sleep(180)  # 3 minute intervals
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(300)
    
    def run(self):
        """Start the bot"""
        self.logger.info("Starting AeroEyeBot...")
        
        # Start monitoring in separate thread
        monitor_thread = threading.Thread(target=self.monitor_flights, daemon=True)
        monitor_thread.start()
        
        # Start bot polling
        self.logger.info("Bot is ready! Send /start to begin.")
        self.bot.infinity_polling(none_stop=True, interval=0)

# Main execution
if __name__ == "__main__":
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_ACTUAL_TOKEN_HERE')  # Replace with your actual bot token
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your bot token in the code!")
        print("Get your token from @BotFather on Telegram")
        exit(1)
    
    try:
        bot = AeroEyeBot(BOT_TOKEN)
        bot.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        logging.error(f"Fatal error: {e}")
