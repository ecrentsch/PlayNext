from flask import Flask, render_template, request, jsonify
from recommender import GameRecommender
import traceback

app = Flask(__name__)
recommender = GameRecommender()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/recommend', methods=['POST'])
def recommend():
    """API endpoint to get recommendations"""
    try:
        data = request.json
        
        steam_input = data.get('steam_id', '').strip()
        min_rating = int(data.get('min_rating', 0))
        sort_by = data.get('sort_by', 'match')
        
        # New parameters
        price_min = float(data.get('price_min', 0))
        price_max = float(data.get('price_max', 999))
        price_range = (price_min, price_max) if price_min > 0 or price_max < 999 else None
        
        show_recent_only = data.get('show_recent_only', False)
        
        if not steam_input:
            return jsonify({'error': 'Please provide a Steam ID or username'})
        
        # Try to convert username to Steam ID if needed
        steam_id = steam_input
        if not steam_input.isdigit():
            steam_id = recommender.steam_api.get_steam_id(steam_input)
            if not steam_id:
                return jsonify({'error': 'Could not find Steam user. Make sure your profile is public and the username is correct!'})
        
        # Get recommendations
        results = recommender.get_recommendations(
            steam_id, 
            min_rating, 
            sort_by,
            price_range,
            show_recent_only
        )
        
        return jsonify(results)
    
    except Exception as e:
        # Better error handling
        error_msg = str(e)
        print(f"Error: {error_msg}")
        print(traceback.format_exc())
        
        return jsonify({
            'error': f'An error occurred: {error_msg}. Please try again or check if your Steam profile is public.'
        })

if __name__ == '__main__':
    app.run(debug=True)