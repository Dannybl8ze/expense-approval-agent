CREATE TABLE user_profile (
    id INT PRIMARY KEY,
    bio TEXT
);

CREATE TABLE posts (
    id INT PRIMARY KEY,
    title TEXT,
    content TEXT,
    created_at TIMESTAMP
);

CREATE TABLE comments (
    id INT PRIMARY KEY,
    post_id INT,
    body TEXT
);
