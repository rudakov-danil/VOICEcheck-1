-- VOICEcheck PostgreSQL initialization script
-- This script is run automatically on first container startup

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Note: Tables are created by Alembic migrations, not by this script
-- This script only sets up extensions

-- Verify database connection
SELECT 'VOICEcheck database initialized successfully' as message;