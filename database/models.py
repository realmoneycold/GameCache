import uuid
import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Numeric, String, DateTime, ForeignKey, Index, Enum as SQLEnum, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.db import Base

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"

class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    api_product_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    base_usd_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(default=True, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="product")

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    exact_amount_uzs: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tiyin_suffix: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus, name="order_status_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=OrderStatus.PENDING,
        server_default=text("'pending'"),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), 
        nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="orders")
    product: Mapped["Product"] = relationship("Product", back_populates="orders")

    __table_args__ = (
        # Partial unique index to strictly avoid concurrency race conditions where
        # multiple active/pending payments could share the exact same amount + tiyin suffix combination.
        # This ensures payment routing uniquely maps to one and only one pending order.
        Index(
            "uq_pending_payment_suffix",
            "exact_amount_uzs",
            "tiyin_suffix",
            unique=True,
            postgresql_where=text("status = 'pending'")
        ),
    )

class UnmappedPayment(Base):
    __tablename__ = "unmapped_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    received_amount_uzs: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    parsed_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_resolved: Mapped[bool] = mapped_column(default=False, server_default=text("false"), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
