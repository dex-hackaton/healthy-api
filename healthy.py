import databases
import sqlalchemy
from marshmallow import Schema, fields
from starlette.applications import Starlette
from starlette.config import Config
from starlette.responses import JSONResponse
from starlette.routing import Route


config = Config('.env')
DATABASE_URL = config('DATABASE_URL')
metadata = sqlalchemy.MetaData()

# Entities

activities = sqlalchemy.Table(
    "activities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("active", sqlalchemy.Boolean),
)

database = databases.Database(DATABASE_URL)


# Routing

async def list_activities(request):
    query = activities.select()
    results = await database.fetch_all(query)
    return JSONResponse([
        {
            "id": result["id"],
            "name": result["name"]
        } for result in results
    ])


app = Starlette(
    debug=True,
    routes=[
        Route('/activities', list_activities),
    ],
    on_startup=[database.connect],
    on_shutdown=[database.disconnect])