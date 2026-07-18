from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Boolean,
    UniqueConstraint,
)
from .database import Base

# bay_ prefix so tables coexist with AI Business Assistant on the same Postgres


class User(Base):
    """Human or agent account (seller / buyer / both). Linked to main app via SSO."""

    __tablename__ = "bay_users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    # human | agent | admin
    account_type = Column(String, default="human", index=True)
    bio = Column(Text, default="")
    avatar_url = Column(String, default="")
    location = Column(String, default="")
    rating_avg = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    api_key_hash = Column(String, nullable=True)
    api_key_prefix = Column(String, nullable=True, index=True)
    # SSO / bridge: ai-business-assistant + user:123 or agent:45
    source_system = Column(String, nullable=True, index=True)
    external_id = Column(String, nullable=True, index=True)
    # Main app user id when SSO-linked
    main_user_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Category(Base):
    __tablename__ = "bay_categories"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    icon = Column(String, default="")
    sort_order = Column(Integer, default=0)


class Listing(Base):
    __tablename__ = "bay_listings"
    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    category_id = Column(Integer, ForeignKey("bay_categories.id"), nullable=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    kind = Column(String, default="product", index=True)
    price = Column(Float, nullable=False, default=0.0)
    currency = Column(String, default="USD")
    quantity = Column(Integer, default=1)
    status = Column(String, default="active", index=True)
    condition = Column(String, default="new")
    image_url = Column(String, default="")
    images_json = Column(Text, default="[]")
    tags = Column(String, default="")
    location = Column(String, default="")
    shipping_info = Column(Text, default="")
    sale_type = Column(String, default="buy_now")
    views = Column(Integer, default=0)
    source_system = Column(String, nullable=True, index=True)
    external_id = Column(String, nullable=True, index=True)
    external_meta = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Offer(Base):
    __tablename__ = "bay_offers"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("bay_listings.id"), index=True, nullable=False)
    buyer_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    amount = Column(Float, nullable=False)
    message = Column(Text, default="")
    status = Column(String, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "bay_orders"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("bay_listings.id"), index=True, nullable=False)
    buyer_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    seller_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="pending", index=True)
    payment_status = Column(String, default="unpaid", index=True)
    stripe_session_id = Column(String, nullable=True, index=True)
    reserved_qty = Column(Integer, default=0)
    shipping_address = Column(Text, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Review(Base):
    __tablename__ = "bay_reviews"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("bay_orders.id"), unique=True, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    reviewee_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatRoom(Base):
    __tablename__ = "bay_chat_rooms"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    room_type = Column(String, default="public", index=True)
    post_policy = Column(String, default="anyone")
    created_by = Column(Integer, ForeignKey("bay_users.id"), nullable=True)
    listing_id = Column(Integer, ForeignKey("bay_listings.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoomMember(Base):
    __tablename__ = "bay_room_members"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("bay_chat_rooms.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    role = Column(String, default="member")
    joined_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_bay_room_user"),)


class ChatMessage(Base):
    __tablename__ = "bay_chat_messages"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("bay_chat_rooms.id"), index=True, nullable=False)
    sender_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    content = Column(Text, nullable=False)
    msg_type = Column(String, default="text")
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "bay_watchlist"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("bay_users.id"), index=True, nullable=False)
    listing_id = Column(Integer, ForeignKey("bay_listings.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_bay_watch"),)
