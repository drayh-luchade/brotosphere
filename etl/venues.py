"""
venues.py

Major-league venue coordinates for all 32 NFL, 30 NBA, 30 MLB, and 32 NHL
teams. Compiled from public knowledge as of mid-2026 -- accurate enough
for "distance to nearest venue" purposes, but not survey-grade.

OpenStreetMap tagging for "is this an NFL stadium" is inconsistent, and
league membership/venues change over time (relocations, new arenas,
temporary homes during construction) -- so this is a curated list rather
than something scraped from Overpass. A few entries below are worth
re-checking periodically because they're mid-transition as of this
writing:

  - Athletics (MLB): playing at Sutter Health Park in West Sacramento, CA
    through at least 2027 while their permanent Las Vegas stadium is
    built (expected ~2028).
  - Tampa Bay Rays (MLB): playing at George M. Steinbrenner Field in
    Tampa while Tropicana Field is repaired/rebuilt.
  - Utah Mammoth (NHL): formerly the Arizona Coyotes; now in Salt Lake
    City at the Delta Center (shared with the NBA's Utah Jazz), with a
    dedicated downtown arena reportedly planned for later this decade.
  - Washington Commanders (NFL): currently at Northwest Stadium in
    Landover, MD; a new stadium at the RFK Stadium site in DC is planned
    to open later in the decade.

Re-verify before relying on this for anything beyond a hobby project --
and re-run this once a year or so regardless, since venues change less
often than bar happy-hour menus, but they do change.
"""

# league -> list of (team, lat, lon)
VENUES = {
    "nfl": [
        ("Arizona Cardinals", 33.5276, -112.2626),
        ("Atlanta Falcons", 33.7554, -84.4008),
        ("Baltimore Ravens", 39.2780, -76.6227),
        ("Buffalo Bills", 42.7738, -78.7870),
        ("Carolina Panthers", 35.2258, -80.8528),
        ("Chicago Bears", 41.8623, -87.6167),
        ("Cincinnati Bengals", 39.0955, -84.5160),
        ("Cleveland Browns", 41.5061, -81.6995),
        ("Dallas Cowboys", 32.7473, -97.0945),
        ("Denver Broncos", 39.7439, -105.0201),
        ("Detroit Lions", 42.3400, -83.0456),
        ("Green Bay Packers", 44.5013, -88.0622),
        ("Houston Texans", 29.6847, -95.4107),
        ("Indianapolis Colts", 39.7601, -86.1639),
        ("Jacksonville Jaguars", 30.3239, -81.6373),
        ("Kansas City Chiefs", 39.0489, -94.4839),
        ("Las Vegas Raiders", 36.0909, -115.1833),
        ("Los Angeles Chargers", 33.9535, -118.3392),
        ("Los Angeles Rams", 33.9535, -118.3392),
        ("Miami Dolphins", 25.9580, -80.2389),
        ("Minnesota Vikings", 44.9737, -93.2577),
        ("New England Patriots", 42.0909, -71.2643),
        ("New Orleans Saints", 29.9511, -90.0812),
        ("New York Giants", 40.8135, -74.0745),
        ("New York Jets", 40.8135, -74.0745),
        ("Philadelphia Eagles", 39.9008, -75.1675),
        ("Pittsburgh Steelers", 40.4468, -80.0158),
        ("San Francisco 49ers", 37.4030, -121.9700),
        ("Seattle Seahawks", 47.5952, -122.3316),
        ("Tampa Bay Buccaneers", 27.9759, -82.5033),
        ("Tennessee Titans", 36.1665, -86.7713),
        ("Washington Commanders", 38.9078, -76.8645),
    ],
    "nba": [
        ("Atlanta Hawks", 33.7573, -84.3963),
        ("Boston Celtics", 42.3662, -71.0621),
        ("Brooklyn Nets", 40.6826, -73.9754),
        ("Charlotte Hornets", 35.2251, -80.8392),
        ("Chicago Bulls", 41.8807, -87.6742),
        ("Cleveland Cavaliers", 41.4965, -81.6882),
        ("Dallas Mavericks", 32.7905, -96.8103),
        ("Denver Nuggets", 39.7487, -105.0077),
        ("Detroit Pistons", 42.3411, -83.0553),
        ("Golden State Warriors", 37.7680, -122.3877),
        ("Houston Rockets", 29.7508, -95.3621),
        ("Indiana Pacers", 39.7640, -86.1555),
        ("LA Clippers", 33.9456, -118.3417),
        ("Los Angeles Lakers", 34.0430, -118.2673),
        ("Memphis Grizzlies", 35.1382, -90.0505),
        ("Miami Heat", 25.7814, -80.1870),
        ("Milwaukee Bucks", 43.0451, -87.9172),
        ("Minnesota Timberwolves", 44.9795, -93.2760),
        ("New Orleans Pelicans", 29.9490, -90.0821),
        ("New York Knicks", 40.7505, -73.9934),
        ("Oklahoma City Thunder", 35.4634, -97.5151),
        ("Orlando Magic", 28.5392, -81.3839),
        ("Philadelphia 76ers", 39.9012, -75.1720),
        ("Phoenix Suns", 33.4457, -112.0712),
        ("Portland Trail Blazers", 45.5316, -122.6668),
        ("Sacramento Kings", 38.5802, -121.4997),
        ("San Antonio Spurs", 29.4270, -98.4375),
        ("Toronto Raptors", 43.6435, -79.3791),
        ("Utah Jazz", 40.7683, -111.9011),
        ("Washington Wizards", 38.8981, -77.0209),
    ],
    "mlb": [
        ("Arizona Diamondbacks", 33.4455, -112.0667),
        ("Atlanta Braves", 33.8908, -84.4678),
        ("Baltimore Orioles", 39.2838, -76.6217),
        ("Boston Red Sox", 42.3467, -71.0972),
        ("Chicago Cubs", 41.9484, -87.6553),
        ("Chicago White Sox", 41.8299, -87.6338),
        ("Cincinnati Reds", 39.0979, -84.5066),
        ("Cleveland Guardians", 41.4962, -81.6852),
        ("Colorado Rockies", 39.7559, -104.9942),
        ("Detroit Tigers", 42.3390, -83.0485),
        ("Houston Astros", 29.7573, -95.3555),
        ("Kansas City Royals", 39.0517, -94.4803),
        ("Los Angeles Angels", 33.8003, -117.8827),
        ("Los Angeles Dodgers", 34.0739, -118.2400),
        ("Miami Marlins", 25.7781, -80.2196),
        ("Milwaukee Brewers", 43.0280, -87.9712),
        ("Minnesota Twins", 44.9817, -93.2776),
        ("New York Mets", 40.7571, -73.8458),
        ("New York Yankees", 40.8296, -73.9262),
        ("Athletics", 38.5799, -121.5309),
        ("Philadelphia Phillies", 39.9061, -75.1665),
        ("Pittsburgh Pirates", 40.4469, -80.0057),
        ("San Diego Padres", 32.7073, -117.1566),
        ("San Francisco Giants", 37.7786, -122.3893),
        ("Seattle Mariners", 47.5914, -122.3325),
        ("St. Louis Cardinals", 38.6226, -90.1928),
        ("Tampa Bay Rays", 27.9803, -82.5066),
        ("Texas Rangers", 32.7473, -97.0842),
        ("Toronto Blue Jays", 43.6414, -79.3894),
        ("Washington Nationals", 38.8730, -77.0074),
    ],
    "nhl": [
        ("Anaheim Ducks", 33.8078, -117.8765),
        ("Boston Bruins", 42.3662, -71.0621),
        ("Buffalo Sabres", 42.8750, -78.8764),
        ("Calgary Flames", 51.0374, -114.0519),
        ("Carolina Hurricanes", 35.8033, -78.7220),
        ("Chicago Blackhawks", 41.8807, -87.6742),
        ("Colorado Avalanche", 39.7487, -105.0077),
        ("Columbus Blue Jackets", 39.9692, -83.0061),
        ("Dallas Stars", 32.7905, -96.8103),
        ("Detroit Red Wings", 42.3411, -83.0553),
        ("Edmonton Oilers", 53.5469, -113.4977),
        ("Florida Panthers", 26.1584, -80.3255),
        ("Los Angeles Kings", 34.0430, -118.2673),
        ("Minnesota Wild", 44.9447, -93.1011),
        ("Montreal Canadiens", 45.4961, -73.5693),
        ("Nashville Predators", 36.1593, -86.7787),
        ("New Jersey Devils", 40.7336, -74.1710),
        ("New York Islanders", 40.7229, -73.5911),
        ("New York Rangers", 40.7505, -73.9934),
        ("Ottawa Senators", 45.2969, -75.9270),
        ("Philadelphia Flyers", 39.9012, -75.1720),
        ("Pittsburgh Penguins", 40.4395, -79.9892),
        ("San Jose Sharks", 37.3327, -121.9007),
        ("Seattle Kraken", 47.6221, -122.3540),
        ("St. Louis Blues", 38.6266, -90.2026),
        ("Tampa Bay Lightning", 27.9427, -82.4518),
        ("Toronto Maple Leafs", 43.6435, -79.3791),
        ("Utah Mammoth", 40.7683, -111.9011),
        ("Vancouver Canucks", 49.2778, -123.1088),
        ("Vegas Golden Knights", 36.1028, -115.1785),
        ("Washington Capitals", 38.8981, -77.0209),
        ("Winnipeg Jets", 49.8928, -97.1436),
    ],
}
