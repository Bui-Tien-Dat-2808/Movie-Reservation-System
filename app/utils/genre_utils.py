GENRE_MAP_VIETNAMESE = {
    "action": "Hành Động",
    "adventure": "Phiêu Lưu",
    "animation": "Hoạt Hình",
    "comedy": "Hài",
    "crime": "Hình Sự",
    "documentary": "Tài Liệu",
    "drama": "Chính Kịch",
    "family": "Gia Đình",
    "fantasy": "Giả Tượng",
    "history": "Lịch Sử",
    "horror": "Kinh Dị",
    "music": "Âm Nhạc",
    "mystery": "Bí Ẩn",
    "romance": "Lãng Mạn",
    "science fiction": "Khoa Học Viễn Tưởng",
    "sci-fi": "Khoa Học Viễn Tưởng",
    "tv movie": "Phim Truyền Hình",
    "thriller": "Gây Cấn",
    "war": "Chiến Tranh",
    "western": "Miền Tây",
}


def normalize_genre_name(raw_name: str) -> str:
    """
    Normalize genre names to unified Vietnamese titles:
    - Removes 'Phim ' prefix if present
    - Maps English genre names to official Vietnamese counterparts
    - Capitalizes titles properly
    """
    if not raw_name:
        return ""
    cleaned = raw_name.strip()
    if cleaned.lower().startswith("phim "):
        cleaned = cleaned[5:].strip()
    return GENRE_MAP_VIETNAMESE.get(cleaned.lower(), cleaned.title())
