import os
from typing import Optional
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Depends, Body, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
import datetime
import json
import openai
from openai.embeddings_utils import get_embedding
import pinecone
import requests
import numpy as np
import logging



from models.api import (
    DeleteRequest,
    DeleteResponse,
    QueryRequest,
    QueryResponse,
    UpsertRequest,
    UpsertResponse,
)
from datastore.factory import get_datastore
from services.file import get_document_from_file
from services.openai import get_embeddings

from models.models import DocumentMetadata, Source

bearer_scheme = HTTPBearer()
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")
assert BEARER_TOKEN is not None


def validate_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if credentials.scheme != "Bearer" or credentials.credentials != BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return credentials


app = FastAPI(dependencies=[Depends(validate_token)])
app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static")

# Create a sub-application, in order to access just the query endpoint in an OpenAPI schema, found at http://0.0.0.0:8000/sub/openapi.json when the app is running locally
sub_app = FastAPI(
    title="NBA Basketball Knowledge",
    description="Get the context behind NBA stats with access to up to date stats, news and opinions.",
    version="1.0.0",
    servers=[{"url": "https://octopus-app-4yrlx.ondigitalocean.app/"}],
    dependencies=[Depends(validate_token)],
)
app.mount("/sub", sub_app)

index_name = 'kh-chat-app'
pinecone.init(api_key="f0570753-9d5f-4be9-9533-1d912957ed25", environment="us-east1-gcp")

# Connect to the index
index = pinecone.Index(index_name)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)



def filter_game_data(game):
    return {
        "GameEndDateTime": game["GameEndDateTime"],
        "GameID": game["GameID"],
        "Season": game["Season"],
        "SeasonType": game["SeasonType"],
        "Status": game["Status"],
        "Day": game["Day"],
        "DateTime": game["DateTime"],
        "AwayTeam": game["AwayTeam"],
        "HomeTeam": game["HomeTeam"],
        "AwayTeamID": game["AwayTeamID"],
        "HomeTeamID": game["HomeTeamID"],
        "StadiumID": game["StadiumID"],
        "AwayTeamScore": game["AwayTeamScore"],
        "HomeTeamScore": game["HomeTeamScore"],
        "Updated": game["Updated"],
        "IsClosed": game["IsClosed"],
        "NeutralVenue": game["NeutralVenue"],
        "DateTimeUTC": game["DateTimeUTC"],
    }

def create_date_string(year, month, day):
    return f"{year:04d}-{month:02d}-{day:02d}"


@app.get("/games")
async def get_games(day, message):
    logger.info(f"Day pre: {Day}")
    day = day["day"]
    logger.info(f"Day post: {Day}")
    if day:
        api_url = f"https://api.sportsdata.io/v3/nba/scores/json/GamesByDate/{day}?key=48a287166d5d4ecabd71c344439ee80c"
        logger.info(f"API-URL: {api_url}")

        response = requests.get(api_url)
        raw_scores = response.json()
    else:
        raw_scores = "No scores availible for that day"

  
    year, month, day = date.split('-')

    if message:
        # Convert ndarray to list
        info_vector_list = await get_embeddings(message)
    
        # Semantic Search within category
        search = index.query(
          vector=info_vector_list,
          #filter={"Year": {"$eq": year},
          #       "Month": {"$eq": month},
          #       "Day": {"$eq": day}},
          top_k=10,
          include_metadata=True
        )  
    
        search_results = search["matches"]
    else:
      search = "No vector results found"
      
    # Combine JSON files
    combined_results = {}
    combined_results['game_data'] = raw_scores
    combined_results['search_results'] = search_results

    logger.info(f"Day: {day}, Message: {message}")
    logger.info(f"Raw_Scores: {raw_scores}"
                f"Search_Results: {search_results}")
      
    return combined_results

@app.get("/year_standings")
def get_standings(year, message):
    api_url_today = f"https://api.sportsdata.io/v3/nba/scores/json/Standings/{year}?key=48a287166d5d4ecabd71c344439ee80c"
    response = requests.get(api_url_today)
    raw_standings = response.json()
    return raw_standings

@app.get("/allstar_roster")
def get_allstar_roster(year: int, message: str):
    api_url_today = f"https://api.sportsdata.io/v3/nba/stats/json/AllStars/{year}?key=48a287166d5d4ecabd71c344439ee80c"
    response = requests.get(api_url_today)
    raw_all_star_roster = response.json()

    # Perform semantic search - get message vector embedding
    info_vector = get_embedding(message, engine="text-embedding-ada-002")
    info_vector = np.array(info_vector).reshape(1, -1)
    info_vector = info_vector.reshape(-1)

    # Convert ndarray to list
    info_vector_list = info_vector.tolist()

    # Semantic Search within category
    search = index.query(
      vector=info_vector_list,
      filter={"Year": {"$eq": year}},
      top_k=10,
      include_metadata=True
    )  

    search_results = search["matches"]

    # Combine JSON files
    combined_results = {}
    combined_results['all_star_roster'] = raw_all_star_roster
    combined_results['search_results'] = search_results
      
    return json.dumps(combined_results)
    
@app.get("/current_roster_list")
def get_current_rosters(team_abv, message):
    api_url_today = f"https://api.sportsdata.io/v3/nba/scores/json/PlayersBasic/{team_abv}?key=48a287166d5d4ecabd71c344439ee80c"
    response = requests.get(api_url_today)
    raw_roster = response.json()
    return raw_roster

@app.get("/player_stats_by_date")
def get_Players_Stats_By_Date(date, player_name, player_id, message):
    api_url_today = f"https://api.sportsdata.io/v3/nba/stats/json/PlayerGameStatsByDate/{date}?key=48a287166d5d4ecabd71c344439ee80c"
    response = requests.get(api_url_today)
    filtered_player_stats_by_date = response.json()
    if player_id:
      for player in filtered_player_stats_by_date:
        if player["PlayerID"] == player_id:
            # Create a dictionary with the desired player stats
              filtered_player_stats = {
                  "StatID": player["StatID"],
                  "TeamID": player["TeamID"],
                  "PlayerID": player["PlayerID"],
                  "Season": player["Season"],
                  "Name": player["Name"],
                  "Team": player["Team"],
                  "Position": player["Position"],
                  "Started": player["Started"],
                  "Updated": player["Updated"],
                  "Games": player["Games"],
                  "Minutes": player["Minutes"],
                  "Seconds": player["Seconds"],
                  "FieldGoalsMade": player["FieldGoalsMade"],
                  "FieldGoalsAttempted": player["FieldGoalsAttempted"],
                  "FieldGoalsPercentage": player["FieldGoalsPercentage"],
                  "EffectiveFieldGoalsPercentage": player["EffectiveFieldGoalsPercentage"],
                  "TwoPointersMade": player["TwoPointersMade"],
                  "TwoPointersAttempted": player["TwoPointersAttempted"],
                  "TwoPointersPercentage": player["TwoPointersPercentage"],
                  "ThreePointersMade": player["ThreePointersMade"],
                  "ThreePointersAttempted": player["ThreePointersAttempted"],
                  "ThreePointersPercentage": player["ThreePointersPercentage"],
                  "FreeThrowsMade": player["FreeThrowsMade"],
                  "FreeThrowsAttempted": player["FreeThrowsAttempted"],
                  "FreeThrowsPercentage": player["FreeThrowsPercentage"],
                  "OffensiveRebounds": player["OffensiveRebounds"],
                  "DefensiveRebounds": player["DefensiveRebounds"],
                  "Rebounds": player["Rebounds"],
                  "OffensiveReboundsPercentage": player["OffensiveReboundsPercentage"],
                  "DefensiveReboundsPercentage": player["DefensiveReboundsPercentage"],
                  "TotalReboundsPercentage": player["TotalReboundsPercentage"],
                  "Assists": player["Assists"],
                  "Steals": player["Steals"],
                  "BlockedShots": player["BlockedShots"],
                  "Turnovers": player["Turnovers"],
                  "PersonalFouls": player["PersonalFouls"],
                  "Points": player["Points"],
                  "TrueShootingAttempts": player["TrueShootingAttempts"],
                  "TrueShootingPercentage": player["TrueShootingPercentage"],
                  "PlayerEfficiencyRating": player["PlayerEfficiencyRating"],
                  "AssistsPercentage": player["AssistsPercentage"],
                  "StealsPercentage": player["StealsPercentage"],
                  "BlocksPercentage": player["BlocksPercentage"],
                  "TurnOversPercentage": player["TurnOversPercentage"],
                  "UsageRatePercentage": player["UsageRatePercentage"],
                  "PlusMinus": player["PlusMinus"],
                  "DoubleDoubles": player["DoubleDoubles"],
                  "TripleDoubles": player["TripleDoubles"]
              }
    if player_name:
      for player in filtered_player_stats_by_date:
        if player["Name"] == player_name:      
            filtered_player_stats = {
                "StatID": player["StatID"],
                "TeamID": player["TeamID"],
                "PlayerID": player["PlayerID"],
                "Season": player["Season"],
                "Name": player["Name"],
                "Team": player["Team"],
                "Position": player["Position"],
                "Started": player["Started"],
                "Updated": player["Updated"],
                "Games": player["Games"],
                "Minutes": player["Minutes"],
                "Seconds": player["Seconds"],
                "FieldGoalsMade": player["FieldGoalsMade"],
                "FieldGoalsAttempted": player["FieldGoalsAttempted"],
                "FieldGoalsPercentage": player["FieldGoalsPercentage"],
                "EffectiveFieldGoalsPercentage": player["EffectiveFieldGoalsPercentage"],
                "TwoPointersMade": player["TwoPointersMade"],
                "TwoPointersAttempted": player["TwoPointersAttempted"],
                "TwoPointersPercentage": player["TwoPointersPercentage"],
                "ThreePointersMade": player["ThreePointersMade"],
                "ThreePointersAttempted": player["ThreePointersAttempted"],
                "ThreePointersPercentage": player["ThreePointersPercentage"],
                "FreeThrowsMade": player["FreeThrowsMade"],
                "FreeThrowsAttempted": player["FreeThrowsAttempted"],
                "FreeThrowsPercentage": player["FreeThrowsPercentage"],
                "OffensiveRebounds": player["OffensiveRebounds"],
                "DefensiveRebounds": player["DefensiveRebounds"],
                "Rebounds": player["Rebounds"],
                "OffensiveReboundsPercentage": player["OffensiveReboundsPercentage"],
                "DefensiveReboundsPercentage": player["DefensiveReboundsPercentage"],
                "TotalReboundsPercentage": player["TotalReboundsPercentage"],
                "Assists": player["Assists"],
                "Steals": player["Steals"],
                "BlockedShots": player["BlockedShots"],
                "Turnovers": player["Turnovers"],
                "PersonalFouls": player["PersonalFouls"],
                "Points": player["Points"],
                "TrueShootingAttempts": player["TrueShootingAttempts"],
                "TrueShootingPercentage": player["TrueShootingPercentage"],
                "PlayerEfficiencyRating": player["PlayerEfficiencyRating"],
                "AssistsPercentage": player["AssistsPercentage"],
                "StealsPercentage": player["StealsPercentage"],
                "BlocksPercentage": player["BlocksPercentage"],
                "TurnOversPercentage": player["TurnOversPercentage"],
                "UsageRatePercentage": player["UsageRatePercentage"],
                "PlusMinus": player["PlusMinus"],
                "DoubleDoubles": player["DoubleDoubles"],
                "TripleDoubles": player["TripleDoubles"]
            }
    return filtered_player_stats

@app.on_event("startup")
async def startup():
    global datastore
    datastore = await get_datastore()


def start():
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
