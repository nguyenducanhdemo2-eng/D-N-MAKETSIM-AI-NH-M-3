# ==============================================================================
# CLUSTERING.PY - BƯỚC 2: PHÂN TÍCH NHÓM TÂM LÝ KHÁCH HÀNG (K-MEANS)
# ==============================================================================

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

from config import NUM_CLUSTERS, RANDOM_STATE


def cluster_customer_psychology(df: pd.DataFrame, n_clusters: int = NUM_CLUSTERS) -> dict:
    """
    Nhận bảng dữ liệu văn bản thô (xu hướng + tin tức), vector hóa bằng TF-IDF,
    rồi phân cụm bằng K-Means (scikit-learn) thành n_clusters nhóm tâm lý khách hàng.

    Đầu vào : hàng vạn xu hướng/tin tức lộn xộn (dạng text)
    Đầu ra  : n_clusters nhóm tâm lý khách hàng chính của ngày

    Trả về dict:
        {
            "labeled_df": DataFrame gốc + cột 'cluster',
            "cluster_keywords": {0: [tu_khoa,...], 1: [...], 2: [...]},
            "cluster_sizes": {0: n, 1: n, 2: n},
        }
    """
    print("[2] BƯỚC 2: PHÂN TÍCH NHÓM TÂM LÝ KHÁCH HÀNG (K-MEANS)\n")
    print(f"    - Đầu vào: {len(df)} bản ghi xu hướng/tin tức lộn xộn")

    vectorizer = TfidfVectorizer(max_features=500, min_df=1)
    X = vectorizer.fit_transform(df["text"])

    kmeans = KMeans(n_clusters=n_clusters, random_state=RANDOM_STATE, n_init=10)
    labels = kmeans.fit_predict(X)

    df = df.copy()
    df["cluster"] = labels

    # Lấy từ khóa đại diện cho mỗi cụm (top trọng số TF-IDF tại tâm cụm)
    terms = vectorizer.get_feature_names_out()
    cluster_keywords = {}
    for c in range(n_clusters):
        center = kmeans.cluster_centers_[c]
        top_idx = center.argsort()[::-1][:8]
        cluster_keywords[c] = [terms[i] for i in top_idx]

    cluster_sizes = df["cluster"].value_counts().to_dict()

    print(f"    - Đầu ra: {n_clusters} nhóm tâm lý khách hàng chính của ngày")
    for c in range(n_clusters):
        print(f"        Nhóm {c} ({cluster_sizes.get(c, 0)} bản ghi): "
              f"{', '.join(cluster_keywords[c][:5])}")
    print()

    return {
        "labeled_df": df,
        "cluster_keywords": cluster_keywords,
        "cluster_sizes": cluster_sizes,
    }
def get_cluster_insights(df):
    """Tạo báo cáo chi tiết cho từng cụm"""
    insights = {}
    for cluster_id in df['cluster'].unique():
        cluster_df = df[df['cluster'] == cluster_id]
        insights[cluster_id] = {
            "avg_weight": cluster_df['weight'].mean(),
            "top_source": cluster_df['source'].mode()[0],
            "sample": cluster_df['text'].iloc[0]
        }
    return insights


if __name__ == "__main__":
    from data_collector import collect_all
    raw_df = collect_all()
    result = cluster_customer_psychology(raw_df)
    print(result["labeled_df"].head())

