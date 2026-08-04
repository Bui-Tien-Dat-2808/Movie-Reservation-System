"""Normalize 13 Vietnamese genres and remove English genre duplicates

Revision ID: normalize_13_vietnamese_genres
Revises: add_voucher_fields_to_reservations
Create Date: 2026-08-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'normalize_13_vietnamese_genres'
down_revision = 'add_voucher_fields_to_reservations'
branch_labels = None
depends_on = None

GENRE_MAP = {
    'action': 'Hành Động',
    'adventure': 'Phiêu Lưu',
    'animation': 'Hoạt Hình',
    'comedy': 'Hài',
    'crime': 'Hình Sự',
    'drama': 'Chính Kịch',
    'family': 'Gia Đình',
    'fantasy': 'Giả Tượng',
    'horror': 'Kinh Dị',
    'mystery': 'Bí Ẩn',
    'romance': 'Lãng Mạn',
    'science fiction': 'Khoa Học Viễn Tưởng',
    'sci-fi': 'Khoa Học Viễn Tưởng',
    'thriller': 'Gây Cấn',
}


def upgrade() -> None:
    # 1. Update genres starting with 'Phim ' to remove prefix
    op.execute("UPDATE genres SET name = REGEXP_REPLACE(name, '^Phim\\s+', '', 'i') WHERE name ILIKE 'Phim %';")

    # 2. Migrate movie_genres mappings from English genre IDs to Vietnamese genre IDs if present
    for en_name, vi_name in GENRE_MAP.items():
        op.execute(f"""
            DO $$
            DECLARE
                en_id INT;
                vi_id INT;
            BEGIN
                SELECT id INTO en_id FROM genres WHERE LOWER(name) = '{en_name}';
                SELECT id INTO vi_id FROM genres WHERE LOWER(name) = '{vi_name.lower()}';
                IF en_id IS NOT NULL AND vi_id IS NOT NULL THEN
                    INSERT INTO movie_genres (movie_id, genre_id)
                    SELECT movie_id, vi_id FROM movie_genres WHERE genre_id = en_id
                    ON CONFLICT DO NOTHING;
                    DELETE FROM movie_genres WHERE genre_id = en_id;
                    DELETE FROM genres WHERE id = en_id;
                END IF;
            END $$;
        """)


def downgrade() -> None:
    pass
