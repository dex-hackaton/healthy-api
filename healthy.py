import databases
import sqlalchemy
import uvicorn
import jwt
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.requests import Request
from authlib.integrations.starlette_client import OAuth
from starlette_jwt import JWTAuthenticationBackend

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

users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("picture", sqlalchemy.String)
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

        users_found = await database.fetch_all(users.count().where(users.c.email == user["email"]))
        users_found = users_found[0]

        if users_found == 0:
            await database.execute(
                users.insert().values(
                    email=user["email"],
                    name=user["name"],
                    picture=user["picture"]
                )
            )
        encoded_jwt = jwt.encode({
            "email": user["email"],
            "name": user["name"],
            "picture": user["picture"]
        }, config("JWT_KEY"), algorithm='HS256')

        return RedirectResponse("https://healthy.adds.md/?token=" + encoded_jwt)


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
        Middleware(SessionMiddleware, secret_key=config('SESSION_SECRET')),
        Middleware(AuthenticationMiddleware, backend=JWTAuthenticationBackend(secret_key=config("JWT_KEY"), prefix='JWT'))
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
