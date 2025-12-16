-- Create form_schemas table
CREATE TABLE IF NOT EXISTS form_schemas (
    id SERIAL PRIMARY KEY,
    form_id VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    schema_json JSONB NOT NULL,
    form_info JSONB,
    meta_data TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create form_submissions table
CREATE TABLE IF NOT EXISTS form_submissions (
    id SERIAL PRIMARY KEY,
    form_id VARCHAR(100) NOT NULL,
    submission_data JSONB NOT NULL,
    form_info JSONB,
    meta_data TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(100), 
    session_id VARCHAR(255),
    FOREIGN KEY (form_id) REFERENCES form_schemas(form_id) ON DELETE CASCADE
);

-- Create index for better performance
CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id ON form_submissions(form_id);
CREATE INDEX IF NOT EXISTS idx_form_submissions_submitted_at ON form_submissions(submitted_at);