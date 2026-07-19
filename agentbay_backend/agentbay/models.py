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
    # Escrow / seller payout
    # payment_method: stripe | crypto
    payment_method = Column(String, default="stripe", index=True)
    crypto_chain = Column(String, default="")  # eth | sol | btc | xrp when crypto
    crypto_tx_hash = Column(String, default="")
    platform_fee = Column(Float, default=0.0)
    seller_net = Column(Float, default=0.0)
    # payout_status: none | held | awaiting_seller_details | ready | released | failed
    payout_status = Column(String, default="none", index=True)
    payout_method = Column(String, default="")  # bank | crypto
    payout_reference = Column(String, default="")
    payout_notes = Column(Text, default="")
    payout_destination_json = Column(Text, default="{}")
    escrow_held_at = Column(DateTime, nullable=True)
    seller_delivered_at = Column(DateTime, nullable=True)
    buyer_confirmed_at = Column(DateTime, nullable=True)
    payout_released_at = Column(DateTime, nullable=True)
    payout_released_by = Column(Integer, ForeignKey("bay_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SellerPayoutProfile(Base):
    """Seller bank + crypto destinations — required before escrow release."""

    __tablename__ = "bay_seller_payout_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("bay_users.id"), unique=True, nullable=False, index=True)
    preferred_method = Column(String, default="bank")  # bank | crypto
    # Bank transfer
    bank_account_name = Column(String, default="")
    bank_name = Column(String, default="")
    bank_country = Column(String, default="")
    bank_currency = Column(String, default="USD")
    bank_iban = Column(String, default="")
    bank_account_number = Column(String, default="")
    bank_routing = Column(String, default="")
    bank_sort_code = Column(String, default="")
    bank_swift = Column(String, default="")
    # Crypto wallets (receive payouts when buyer paid in crypto)
    crypto_eth = Column(String, default="")
    crypto_sol = Column(String, default="")
    crypto_btc = Column(String, default="")
    crypto_xrp = Column(String, default="")
    crypto_xrp_tag = Column(String, default="")
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
