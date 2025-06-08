"""Initial schema

Revision ID: 81f4a98a9213
Revises: 
Create Date: 2025-06-08 00:00:00.000000

"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

# Configure logger
logger = logging.getLogger('alembic.migration')

# revision identifiers, used by Alembic.
revision: str = '81f4a98a9213'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    # Create the table with UUID primary key for both databases
    op.create_table(
        'translated_messages',
        sa.Column('id', sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=False),
        sa.Column('tweet_id', sa.String(length=255), nullable=False),
        sa.Column('tweet_url', sa.String(length=512), nullable=False),
        sa.Column('parent_tweet_id', sa.String(length=255), nullable=True),
        sa.Column('character_name', sa.String(length=128), nullable=False),
        sa.Column('llm_provider', sa.String(length=255), nullable=True),
        sa.Column('translation_text', sa.Text(), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=False),
        # Use timestamp with time zone for both databases
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), 
                 server_default=sa.text('current_timestamp()'),
                 nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    # Create indexes for efficient lookups - compatible with both databases
    op.create_index(
        'idx_translated_messages_telegram_message_id', 
        'translated_messages', 
        ['telegram_message_id'], 
        unique=False
    )
    op.create_index(
        'idx_translated_messages_tweet_id', 
        'translated_messages', 
        ['tweet_id'], 
        unique=False
    )
    op.create_index(
        'idx_translated_messages_parent_tweet_id', 
        'translated_messages', 
        ['parent_tweet_id'], 
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    try:
        op.drop_index('idx_translated_messages_telegram_message_id', table_name='translated_messages')
        op.drop_index('idx_translated_messages_tweet_id', table_name='translated_messages')
        op.drop_index('idx_translated_messages_parent_tweet_id', table_name='translated_messages')
        logger.info("Dropped indexes from translated_messages table")
    except Exception as e:
        logger.warning(f"Error dropping indexes: {str(e)}")
    
    # Drop the table - same for both databases with UUID primary key
    op.drop_table('translated_messages')
