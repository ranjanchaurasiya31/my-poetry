from fastapi import FastAPI, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from datetime import datetime
import os
from fastapi import Response
from starlette.middleware.sessions import SessionMiddleware
import uuid
from dotenv import load_dotenv
load_dotenv()
from passlib.context import CryptContext

DATABASE_URL = "sqlite:///./poetry.db"
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Models
class Poem(Base):
    __tablename__ = "poems"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    likes = relationship("Like", back_populates="poem")
    comments = relationship("Comment", back_populates="poem")

class Like(Base):
    __tablename__ = "likes"
    id = Column(Integer, primary_key=True, index=True)
    poem_id = Column(Integer, ForeignKey("poems.id"))
    value = Column(Integer)  
    session_id = Column(String, nullable=False)  
    poem = relationship("Poem", back_populates="likes")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    poem_id = Column(Integer, ForeignKey("poems.id"))
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    poem = relationship("Poem", back_populates="comments")

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create tables
if not os.path.exists("./poetry.db"):
    Base.metadata.create_all(bind=engine)

# Script to add a new admin
if __name__ == "__main__":
    import getpass
    from sqlalchemy.orm import Session
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    username = input("Enter new admin username: ")
    password = getpass.getpass("Enter new admin password: ")
    password_hash = pwd_context.hash(password)
    if db.query(Admin).filter(Admin.username == username).first():
        print("Admin with this username already exists.")
    else:
        admin = Admin(username=username, password_hash=password_hash)
        db.add(admin)
        db.commit()
        print(f"Admin '{username}' created successfully.")
    db.close()

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.username == username).first()
    if admin and pwd_context.verify(password, admin.password_hash):
        request.session["admin"] = True
        request.session["admin_username"] = username
        return RedirectResponse("/", status_code=302)
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)

@app.get("/poems/{poem_id}", response_class=HTMLResponse)
def poem_detail(request: Request, poem_id: int, db: Session = Depends(get_db)):
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        return HTMLResponse("Poem not found", status_code=404)
    is_admin = request.session.get("admin", False)
    session_id = request.session.get("sid")
    likes = sum(1 for l in poem.likes if l.value == 1)
    dislikes = sum(1 for l in poem.likes if l.value == -1)
    user_like = None
    if session_id:
        for l in poem.likes:
            if l.session_id == session_id:
                user_like = l.value
    created_at_str = poem.created_at.strftime('%Y-%m-%d') if isinstance(poem.created_at, datetime) else str(poem.created_at)[:10]
    # Format comment dates as well
    comments = []
    for c in poem.comments:
        c_date = c.created_at.strftime('%Y-%m-%d') if isinstance(c.created_at, datetime) else str(c.created_at)[:10]
        comments.append({"id": c.id, "content": c.content, "created_at": c_date})
    return templates.TemplateResponse("poem_detail.html", {
        "request": request,
        "poem": poem,
        "likes": likes,
        "dislikes": dislikes,
        "user_like": user_like,
        "is_admin": is_admin,
        "created_at": created_at_str,
        "comments": comments
    })

# Update home page to only show cards with title and like/dislike counts
@app.get("/", response_class=HTMLResponse)
def read_poems(request: Request, db: Session = Depends(get_db)):
    poems = db.query(Poem).order_by(Poem.created_at.desc()).all()
    is_admin = request.session.get("admin", False)
    session_id = request.session.get("sid")
    poems_with_counts = []
    for poem in poems:
        likes = sum(1 for l in poem.likes if l.value == 1)
        dislikes = sum(1 for l in poem.likes if l.value == -1)
        user_like = None
        if session_id:
            for l in poem.likes:
                if l.session_id == session_id:
                    user_like = l.value
        # Format date as string
        created_at_str = poem.created_at.strftime('%Y-%m-%d') if isinstance(poem.created_at, datetime) else str(poem.created_at)[:10]
        poems_with_counts.append({
            "id": poem.id,
            "title": poem.title,
            "likes": likes,
            "dislikes": dislikes,
            "user_like": user_like,
            "created_at": created_at_str
        })
    return templates.TemplateResponse("index.html", {"request": request, "poems": poems_with_counts, "is_admin": is_admin})

@app.post("/poems")
def create_poem(request: Request, title: str = Form(...), content: str = Form(...), db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    poem = Poem(title=title, content=content)
    db.add(poem)
    db.commit()
    db.refresh(poem)
    return RedirectResponse("/", status_code=302)

@app.post("/poems/{poem_id}/like")
def like_poem(request: Request, poem_id: int, value: int = Form(...), db: Session = Depends(get_db)):
    # Use session id for per-user like/dislike
    session_id = request.session.get("sid")
    if not session_id:
        session_id = str(uuid.uuid4())
        request.session["sid"] = session_id
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        raise HTTPException(status_code=404, detail="Poem not found")
    # Check if this session already liked/disliked
    existing = db.query(Like).filter(Like.poem_id == poem_id, Like.session_id == session_id).first()
    if existing:
        if existing.value == value:
            db.delete(existing) 
            db.commit()
            return RedirectResponse("/", status_code=302)
        else:
            existing.value = value  
            db.commit()
            return RedirectResponse("/", status_code=302)
    like = Like(poem_id=poem_id, value=value, session_id=session_id)
    db.add(like)
    db.commit()
    return RedirectResponse("/", status_code=302)

@app.post("/poems/{poem_id}/comment")
def comment_poem(request: Request, poem_id: int, content: str = Form(...), db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        raise HTTPException(status_code=404, detail="Poem not found")
    comment = Comment(poem_id=poem_id, content=content)
    db.add(comment)
    db.commit()
    return RedirectResponse("/", status_code=302)

@app.get("/poems/{poem_id}/edit", response_class=HTMLResponse)
def edit_poem_form(request: Request, poem_id: int, db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        return RedirectResponse("/login", status_code=302)
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        return HTMLResponse("Poem not found", status_code=404)
    return templates.TemplateResponse("edit_poem.html", {"request": request, "poem": poem})

@app.post("/poems/{poem_id}/edit")
def edit_poem(request: Request, poem_id: int, title: str = Form(...), content: str = Form(...), db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        raise HTTPException(status_code=404, detail="Poem not found")
    poem.title = title
    poem.content = content
    db.commit()
    return RedirectResponse("/", status_code=302)

@app.post("/poems/{poem_id}/delete")
def delete_poem(request: Request, poem_id: int, db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    poem = db.query(Poem).filter(Poem.id == poem_id).first()
    if not poem:
        raise HTTPException(status_code=404, detail="Poem not found")
    db.delete(poem)
    db.commit()
    return RedirectResponse("/", status_code=302)

@app.post("/comments/{comment_id}/delete")
def delete_comment(request: Request, comment_id: int, db: Session = Depends(get_db)):
    if not request.session.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    poem_id = comment.poem_id
    db.delete(comment)
    db.commit()
    return RedirectResponse(f"/poems/{poem_id}", status_code=302) 