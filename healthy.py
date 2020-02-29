from datetime import datetime

import databases
import sqlalchemy
import uvicorn
import jwt
from sqlalchemy import and_, text
from starlette.applications import Starlette
from starlette.authentication import requires
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
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("picture", sqlalchemy.String)
)

events = sqlalchemy.Table(
    "events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String),
    sqlalchemy.Column("start_time", sqlalchemy.DateTime),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("place", sqlalchemy.String),
    sqlalchemy.Column("paid", sqlalchemy.Boolean),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("organization_description", sqlalchemy.String),
    sqlalchemy.Column("paid_description", sqlalchemy.String),
    sqlalchemy.Column("activity", sqlalchemy.String),
)

event_visitors = sqlalchemy.Table(
    "event_visitors",
    metadata,
    sqlalchemy.Column("user_id", sqlalchemy.String),
    sqlalchemy.Column("event_id", sqlalchemy.String)
)

event_likes = sqlalchemy.Table(
    "event_likes",
    metadata,
    sqlalchemy.Column("user_id", sqlalchemy.String),
    sqlalchemy.Column("event_id", sqlalchemy.String)
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
        users_found = users_found[0][0]

        if users_found == 0:
            await database.execute(
                users.insert().values(
                    email=user["email"],
                    name=user["name"],
                    picture=user["picture"]
                )
            )

        user_found = await database.fetch_one(users.select().where(users.c.email == user["email"]))
        encoded_jwt = jwt.encode({
            "username": str(user_found['id']),
            "email": user["email"],
            "name": user["name"],
            "picture": user["picture"]
        }, config("JWT_KEY"), algorithm='HS256')

        return RedirectResponse("https://healthy.adds.md/?token=" + encoded_jwt.decode("utf-8"))


app = Starlette(
    debug=True,
    routes=[
        Route('/login/{provider}', endpoint=login),
        Route('/auth/{provider}', endpoint=auth),
    ],
    on_startup=[database.connect],
    on_shutdown=[database.disconnect],
    middleware=[
        Middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'],
                   allow_credentials=True),
        Middleware(SessionMiddleware, secret_key=config('SESSION_SECRET')),
        Middleware(AuthenticationMiddleware, backend=JWTAuthenticationBackend(
            secret_key=config("JWT_KEY"),
            prefix='JWT'
        ))
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


@app.route("/event", ["POST"])
@requires('authenticated')
async def add_event(request):
    req = await request.json()
    await database.execute(
        events.insert().values(
            title=req['title'],
            start_time=datetime.strptime(req['start_time'], '%Y-%m-%d %H:%M'),
            city=req['city'],
            place=req['place'],
            paid=req['paid'],
            description=req['description'],
            organization_description=req['organization_description'],
            paid_description=req['paid_description'],
            activity=req['activity']
        )
    )
    return JSONResponse({"status": "ok"})


@app.route("/event/participation", ["POST"])
@requires('authenticated')
async def participate(request):
    await database.execute(
        event_visitors.insert().values(
            user_id=request.user.username,
            event_id=request.query_params['event']
        )
    )
    return JSONResponse({"status": "ok"})


@app.route("/event/participation", ["DELETE"])
@requires('authenticated')
async def participate(request):
    await database.execute(
        event_visitors.delete().where(
            and_(
                event_visitors.c.user_id == request.user.username,
                event_visitors.c.event_id == request.query_params['event']
            )
        )
    )
    return JSONResponse({"status": "ok"})


@app.route("/event/participation", ["GET"])
async def get_participators(request):
    query = text(
            """
            select u.id, u.name, u.picture from event_visitors ev
            join users u on ev.user_id = u.id
            where ev.event_id = :event_id
            """
        )
    query = query.bindparams(event_id=request.query_params['event'])
    participants = await database.fetch_all(
        query
    )

    return JSONResponse([{
        "user_id": str(p['id']),
        "picture": p['picture'],
        "name": p['name']
    } for p in participants])


@app.route("/event/like", ["POST"])
@requires('authenticated')
async def participate(request):
    await database.execute(
        event_likes.insert().values(
            user_id=request.user.username,
            event_id=request.query_params['event']
        )
    )
    return JSONResponse({"status": "ok"})


@app.route("/event/like", ["DELETE"])
@requires('authenticated')
async def participate(request):
    await database.execute(
        event_likes.delete().where(
            and_(
                event_visitors.c.user_id == request.user.username,
                event_visitors.c.event_id == request.query_params['event']
            )
        )
    )
    return JSONResponse({"status": "ok"})


@app.route("/event", ["GET"])
async def get_events(request):
    date_from = datetime.now()
    if 'date_from' in request.query_params and request.query_params['date_from'] is not None:
        date_from = datetime.strptime(request.query_params['date_from'], '%Y-%m-%d')

    date_to = None
    if 'date_to' in request.query_params and request.query_params['date_to'] is not None:
        date_to = datetime.strptime(request.query_params['date_to'], '%Y-%m-%d')

    if date_to is not None:
        query = and_(
            events.c.start_time >= date_from,
            events.c.start_time <= date_to
        )
    else:
        query = events.c.start_time >= date_from

    if 'paid' in request.query_params and request.query_params['paid'] is not None:
        query = and_(
            query,
            events.c.paid == (request.query_params['paid'] in ['1', 1, 'true'])
        )

    if 'activity' in request.query_params and request.query_params['activity'] is not None:
        query = and_(
            query,
            events.c.activity == request.query_params['activity']
        )

    results = await database.fetch_all(
        events.select(query)
    )

    likes = []

    if request.user.is_authenticated:
        likes = await database.fetch_all(
            event_likes.select().where(
                event_likes.c.user_id == request.user.username
            )
        )

    return JSONResponse(
        [{
            "id": str(r["id"]),
            "title": r["title"],
            "start_time": r["start_time"].strftime('%Y-%m-%d %H:%M'),
            "city": r["city"],
            "place": r["place"],
            "paid": r["paid"],
            "description": r["description"],
            "organization_description": r["organization_description"],
            "paid_description": r["paid_description"],
            "activity": r["activity"],
            "like":  len(list(filter(lambda like: str(like['event_id']) == str(r["id"]), likes))) > 0
        } for r in results]
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8001)
