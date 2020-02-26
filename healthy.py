import databases
import sqlalchemy
import uvicorn
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from authlib.integrations.starlette_client import OAuth

config = Config('.env')
DATABASE_URL = config('DATABASE_URL')
metadata = sqlalchemy.MetaData()
oauth = OAuth(config)
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)
oauth.register(
    name='github',
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'user:email read:user'},
)

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

async def login(request: Request):
    redirect_uri = 'https://api.healthy.adds.md/auth/' + request.path_params['provider']
    return await oauth.create_client(request.path_params['provider']).authorize_redirect(request, redirect_uri)


async def auth(request: Request):
    if request.path_params['provider'] == "google":
        token = await oauth.google.authorize_access_token(request)
        user = await oauth.google.parse_id_token(request, token)
        return JSONResponse(dict(user))
    if request.path_params['provider'] == "github":
        token = await oauth.github.authorize_access_token(request)
        user = oauth.github.get('user')
        return JSONResponse(dict(user))


app = Starlette(
    debug=True,
    routes=[
        Route('/login/{provider}', endpoint=login),
        Route('/auth/{provider}', endpoint=auth),
    ],
    on_startup=[database.connect],
    on_shutdown=[database.disconnect],
    middleware=[
        Middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'], allow_credentials=True),
        Middleware(SessionMiddleware, secret_key=config.get('SESSION_SECRET'))
    ]
)


@app.route("/activities")
async def list_activities(request):
    query = activities.select()
    results = await database.fetch_all(query)
    return JSONResponse([
        {
            "id": result["id"],
            "name": result["name"]
        } for result in results
    ])


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8001)