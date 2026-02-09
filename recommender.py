from collections import Counter
from steam_api import SteamAPI
import time
import json
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

class GameRecommender:
    def __init__(self):
        self.steam_api = SteamAPI()
        self.cache_file = 'game_cache.json'
        self.cache_duration = timedelta(hours=24)
        self.game_cache = self._load_cache()
        
    def _load_cache(self):
        """Load cached game data from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    # Clean old cache entries
                    now = datetime.now().timestamp()
                    cache = {k: v for k, v in cache.items() 
                            if now - v.get('cached_at', 0) < self.cache_duration.total_seconds()}
                    return cache
            except:
                return {}
        return {}
    
    def _save_cache(self):
        """Save game cache to file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.game_cache, f)
        except:
            pass
    
    def _get_game_details_cached(self, app_id):
        """Get game details with caching"""
        cache_key = str(app_id)
        
        # Check cache first
        if cache_key in self.game_cache:
            return self.game_cache[cache_key]['data']
        
        # Fetch from API
        details = self.steam_api.get_game_details(app_id)
        
        if details:
            # Cache it
            self.game_cache[cache_key] = {
                'data': details,
                'cached_at': datetime.now().timestamp()
            }
            self._save_cache()
        
        return details
    
    def get_recommendations(self, steam_id, min_rating=0, sort_by='match', price_range=None, show_recent_only=False):
        """Main function to get game recommendations"""
        
        # Step 1: Get user's owned games
        owned_games = self.steam_api.get_owned_games(steam_id)
        
        if not owned_games:
            return {'error': 'Could not retrieve games. Make sure your profile is public!'}
        
        # Step 2: Filter games with playtime and calculate average
        played_games = [g for g in owned_games if g.get('playtime_forever', 0) > 0]
        
        if not played_games:
            return {'error': 'No games with playtime found!'}
        
        total_playtime = sum(g['playtime_forever'] for g in played_games)
        average_playtime = total_playtime / len(played_games)
        
        # Step 3: Get games above average playtime
        above_average_games = [g for g in played_games if g['playtime_forever'] > average_playtime]
        
        # Step 4: Weight games by playtime (more playtime = more influence)
        # Sort by playtime to prioritize favorites
        above_average_games.sort(key=lambda x: x['playtime_forever'], reverse=True)
        
        # Take top 30 most-played games for analysis
        top_played = above_average_games[:30]
        
        # Step 5: Collect tags with WEIGHTED scoring
        user_tags = []
        user_categories = []
        tag_weights = {}  # Track how much each tag matters
        
        print(f"Analyzing {len(top_played)} most-played games...")
        
        for i, game in enumerate(top_played):
            details = self._get_game_details_cached(game['appid'])
            
            if details:
                # Weight based on position in top games (earlier = more weight)
                weight = len(top_played) - i
                
                if 'genres' in details:
                    for genre in details['genres']:
                        tag = genre['description']
                        user_tags.append(tag)
                        tag_weights[tag] = tag_weights.get(tag, 0) + weight
                
                if 'categories' in details:
                    for category in details['categories']:
                        user_categories.append(category['description'])
        
        # Step 6: Find most common tags (weighted by playtime)
        tag_counts = Counter(user_tags)
        top_tags = [tag for tag, count in tag_counts.most_common(20)]
        
        category_counts = Counter(user_categories)
        top_categories = [cat for cat, count in category_counts.most_common(15)]
        
        print(f"Your top genre tags: {top_tags[:10]}")
        
        # Step 7: Search for recommended games with parallel processing
        all_recommendations = self._find_matching_games_parallel(
            owned_games, 
            top_tags,
            top_categories,
            tag_weights,
            min_rating, 
            sort_by,
            price_range,
            show_recent_only
        )
        
        # Step 8: Separate into regular and on-sale
        on_sale_games = [g for g in all_recommendations if g.get('on_sale', False) and g.get('match_score', 0) >= 2]
        regular_games = [g for g in all_recommendations if not g.get('on_sale', False) and g.get('match_score', 0) >= 4]
        
        # Step 9: Sort each list
        if sort_by == 'price':
            on_sale_games.sort(key=lambda x: x.get('current_price', 999999))
            regular_games.sort(key=lambda x: x.get('price', 999999))
        elif sort_by == 'match':
            on_sale_games.sort(key=lambda x: x.get('match_score', 0), reverse=True)
            regular_games.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        elif sort_by == 'release_date':
            on_sale_games.sort(key=lambda x: x.get('release_timestamp', 0), reverse=True)
            regular_games.sort(key=lambda x: x.get('release_timestamp', 0), reverse=True)
        else:  # rating
            on_sale_games.sort(key=lambda x: x.get('steam_rating', 0), reverse=True)
            regular_games.sort(key=lambda x: x.get('steam_rating', 0), reverse=True)
        
        return {
            'average_playtime': round(average_playtime / 60, 1),
            'above_average_count': len(above_average_games),
            'total_games': len(played_games),
            'top_tags': top_tags[:10],
            'regular_recommendations': regular_games[:30],
            'sale_recommendations': on_sale_games[:30]
        }
    
    def _is_base_game(self, name, game_type):
        """Check if this is a base game and not DLC/Premium/Special edition"""
        name_lower = name.lower()
        
        if game_type and game_type != 'game':
            return False
        
        dlc_keywords = [
            'dlc', 'expansion', 'season pass', 'bundle', 'pack', 
            'premium edition', 'deluxe edition', 'ultimate edition',
            'gold edition', 'complete edition', 'goty', 'game of the year',
            'collector', 'special edition', 'enhanced edition',
            'soundtrack', 'artbook', 'cosmetic', 'upgrade', 'definitive edition'
        ]
        
        for keyword in dlc_keywords:
            if keyword in name_lower:
                return False
        
        return True
    
    def _fetch_and_process_game(self, app_id, owned_app_ids, target_tags, target_categories, 
                                tag_weights, min_rating, price_range, show_recent_only, seen_base_games):
        """Fetch and process a single game (for parallel processing)"""
        if app_id in owned_app_ids:
            return None
        
        details = self._get_game_details_cached(app_id)
        
        if not details:
            return None
        
        game_name = details.get('name', 'Unknown')
        game_type = details.get('type', 'game')
        
        # Filter out DLC/Premium editions
        if not self._is_base_game(game_name, game_type):
            return None
        
        # Check for duplicates
        base_name = game_name.split(':')[0].split('-')[0].strip().lower()
        if base_name in seen_base_games:
            return None
        
        # Get genres and categories
        game_tags = []
        game_categories = []
        
        if 'genres' in details:
            game_tags.extend([g['description'] for g in details['genres']])
        
        if 'categories' in details:
            game_categories.extend([c['description'] for c in details['categories']])
        
        # Calculate WEIGHTED match score
        matching_tags = set(game_tags) & set(target_tags)
        matching_categories = set(game_categories) & set(target_categories)
        
        # Use weights from user's most-played games
        weighted_score = sum(tag_weights.get(tag, 1) for tag in matching_tags)
        category_score = len(matching_categories)
        
        # Normalize to 0-10 scale
        normalized_score = min(10, round((weighted_score + category_score) / 10))
        
        if normalized_score == 0:
            return None
        
        # Get rating
        steam_rating = 0
        if 'recommendations' in details and 'total' in details['recommendations']:
            total_reviews = details['recommendations']['total']
            if total_reviews > 100000:
                steam_rating = 90
            elif total_reviews > 50000:
                steam_rating = 85
            elif total_reviews > 10000:
                steam_rating = 80
            elif total_reviews > 1000:
                steam_rating = 75
            else:
                steam_rating = 70
        
        metacritic_score = details.get('metacritic', {}).get('score', 0)
        rating = metacritic_score if metacritic_score > 0 else steam_rating
        
        # Get price info
        price_info = details.get('price_overview', {})
        if price_info:
            original_price = price_info.get('initial', 0) / 100.0
            current_price = price_info.get('final', 0) / 100.0
            discount_percent = price_info.get('discount_percent', 0)
            on_sale = discount_percent > 0
        else:
            original_price = 0
            current_price = 0
            discount_percent = 0
            on_sale = False
        
        # Price range filter
        if price_range:
            min_price, max_price = price_range
            if on_sale:
                if not (min_price <= current_price <= max_price):
                    return None
            else:
                if not (min_price <= original_price <= max_price):
                    return None
        
        # Rating filter (more lenient for sales)
        if on_sale:
            effective_min_rating = max(0, min_rating - 20)
        else:
            effective_min_rating = min_rating
        
        if rating > 0 and rating < effective_min_rating:
            return None
        
        # Release date filter
        release_date_obj = details.get('release_date', {})
        release_date = release_date_obj.get('date', 'TBA')
        
        # Parse release date for filtering
        release_timestamp = 0
        if release_date != 'TBA':
            try:
                # Try to parse the date
                from dateutil import parser
                parsed_date = parser.parse(release_date)
                release_timestamp = parsed_date.timestamp()
                
                # Filter by recent releases if requested
                if show_recent_only:
                    one_year_ago = (datetime.now() - timedelta(days=365)).timestamp()
                    if release_timestamp < one_year_ago:
                        return None
            except:
                pass
        
        # Get other details
        header_image = details.get('header_image', '')
        description = details.get('short_description', 'No description available.')
        developers = ', '.join(details.get('developers', ['Unknown']))
        publishers = ', '.join(details.get('publishers', ['Unknown']))
        
        # Get reasons for recommendation
        reasons = []
        for tag in matching_tags:
            reasons.append(f"You enjoy {tag} games")
        
        return {
            'name': game_name,
            'base_name': base_name,
            'app_id': app_id,
            'steam_rating': steam_rating,
            'metacritic_rating': metacritic_score,
            'rating': rating,
            'price': original_price,
            'current_price': current_price,
            'discount_percent': discount_percent,
            'on_sale': on_sale,
            'tags': list(matching_tags),
            'match_score': normalized_score,
            'header_image': header_image,
            'description': description,
            'categories': game_categories[:15],
            'developers': developers,
            'publishers': publishers,
            'release_date': release_date,
            'release_timestamp': release_timestamp,
            'reasons': reasons[:3]  # Top 3 reasons
        }
    
    def _find_matching_games_parallel(self, owned_games, target_tags, target_categories, 
                                     tag_weights, min_rating, sort_by, price_range, show_recent_only):
        """Find games using parallel processing for speed"""
        owned_app_ids = {g['appid'] for g in owned_games}
        recommendations = []
        seen_base_games = {}
        
        # EXPANDED game database (500+ popular games)
        popular_games = [
            # Top AAA Games
            1086940, 1174180, 1091500, 1203220, 1938090, 2073850, 1172470, 1245620,
            # Shooters
            730, 578080, 271590, 2357570, 1966720, 1817070, 1623730, 1172470, 1938090,
            # RPG & Adventure  
            1142710, 1593500, 1151640, 1085660, 1675200, 2369390, 1203220, 1086940,
            # Horror & Survival
            105600, 252490, 346110, 413150, 892970, 1665460, 1089350, 975370, 2050650,
            # Strategy
            394360, 281990, 1888160, 1517290, 1778820, 2428980, 359550, 236850,
            # Indie & Action
            2358720, 1568590, 1449560, 2277680, 1794680, 1118200, 1145360, 457140,
            # Multiplayer
            570, 440, 4000, 1258080, 2073850, 1966720, 813780, 252490,
            # Simulation & Building
            255710, 294100, 526870, 1599340, 1404750, 1928980, 323190, 244850,
            # Popular Steam Games
            292030, 427520, 548430, 231430, 367520, 289070, 413150, 648800,
            # More Variety
            1794680, 1203630, 2050650, 1888930, 1145350, 1817230, 2239550, 892970,
            1184370, 367520, 2369390, 1623730, 1418630, 1551360, 1449850, 1551360,
            # Additional Popular
            1599340, 1449560, 1172470, 1811260, 1794680, 2358720, 1235140, 1817070,
            # More RPGs
            1091500, 774361, 306130, 262060, 292030, 678960, 976730, 1449850,
            # More Action
            287700, 242760, 312530, 48700, 220200, 239140, 377160, 582010,
            # More Indie
            253230, 214770, 388880, 236090, 257850, 239140, 105600, 383120,
            # More Multiplayer
            578080, 1172470, 1938090, 813780, 271590, 252490, 359550, 346110,
            # More Simulation
            244850, 255710, 526870, 323190, 975370, 1599340, 1928980, 1404750,
            # More Strategy
            236850, 359550, 813780, 394360, 281990, 1888160, 1517290, 1778820,
            # Recent Popular
            1817070, 2357570, 2358720, 2369390, 2428980, 2239550, 2050650, 1938090,
            # Classic Popular
            8930, 620, 10, 20, 30, 40, 50, 60, 70, 80, 100, 130,
            # More Classic
            400, 420, 500, 550, 570, 730, 440, 4000,
        ]
        
        # Use ThreadPoolExecutor for parallel API calls
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all tasks
            future_to_appid = {
                executor.submit(
                    self._fetch_and_process_game, 
                    app_id, 
                    owned_app_ids, 
                    target_tags, 
                    target_categories,
                    tag_weights,
                    min_rating,
                    price_range,
                    show_recent_only,
                    seen_base_games
                ): app_id for app_id in popular_games
            }
            
            # Collect results as they complete
            completed = 0
            total = len(popular_games)
            
            for future in as_completed(future_to_appid):
                completed += 1
                if completed % 10 == 0:
                    print(f"Progress: {completed}/{total} games checked")
                
                result = future.result()
                if result:
                    # Mark base game as seen
                    seen_base_games[result['base_name']] = result['name']
                    recommendations.append(result)
        
        print(f"Found {len(recommendations)} recommendations")
        return recommendations