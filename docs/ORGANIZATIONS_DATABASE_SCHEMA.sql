-- ============================================================================
-- VOICEcheck: Организации и пользователи
-- SQL Schema для Multi-tenancy
-- ============================================================================

-- ============================================================================
-- 1. USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Authentication
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,

    -- Profile
    full_name VARCHAR(255),
    avatar_url VARCHAR(512),

    -- Email verification
    email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR(255),
    email_verification_expires_at TIMESTAMP WITH TIME ZONE,

    -- Password reset
    reset_password_token VARCHAR(255),
    reset_password_expires_at TIMESTAMP WITH TIME ZONE,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- Indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_active ON users(is_active);
CREATE INDEX idx_users_email_verification_token ON users(email_verification_token) WHERE email_verification_token IS NOT NULL;
CREATE INDEX idx_users_reset_password_token ON users(reset_password_token) WHERE reset_password_token IS NOT NULL;

-- Comments
COMMENT ON TABLE users IS 'Пользователи системы';
COMMENT ON COLUMN users.email IS 'Email адрес (уникальный)';
COMMENT ON COLUMN users.password_hash IS 'Хеш пароля (bcrypt)';
COMMENT ON COLUMN users.email_verified IS 'Подтвержден ли email';
COMMENT ON COLUMN users.is_active IS 'Активен ли аккаунт';

-- ============================================================================
-- 2. ORGANIZATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS organizations (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Basic info
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,

    -- Settings (JSONB для гибкости)
    settings JSONB DEFAULT '{
        "max_members": 10,
        "max_storage_gb": 100,
        "allow_invites": true,
        "default_role": "member"
    }'::jsonb,

    -- Subscription/Billing
    subscription_tier VARCHAR(50) DEFAULT 'free',
    subscription_expires_at TIMESTAMP WITH TIME ZONE,

    -- Soft delete
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_organizations_slug ON organizations(slug);
CREATE INDEX idx_organizations_deleted_at ON organizations(deleted_at) WHERE deleted_at IS NOT NULL;

-- Comments
COMMENT ON TABLE organizations IS 'Организации (компании)';
COMMENT ON COLUMN organizations.slug IS 'Уникальный идентификатор для URL';
COMMENT ON COLUMN organizations.settings IS 'Настройки организации (JSON)';
COMMENT ON COLUMN organizations.subscription_tier IS 'Тарифный план: free, pro, enterprise';

-- ============================================================================
-- 3. MEMBERSHIPS TABLE (Organization <-> Users)
-- ============================================================================
CREATE TABLE IF NOT EXISTS memberships (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign keys
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Role in organization
    role VARCHAR(20) NOT NULL DEFAULT 'member',

    -- Invitation flow
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    invited_by_id UUID REFERENCES users(id),
    invitation_token VARCHAR(255),
    invitation_expires_at TIMESTAMP WITH TIME ZONE,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_role CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'active', 'disabled', 'declined')),

    -- One user can have only one membership per organization
    UNIQUE(user_id, organization_id)
);

-- Indexes
CREATE INDEX idx_memberships_user_id ON memberships(user_id);
CREATE INDEX idx_memberships_organization_id ON memberships(organization_id);
CREATE INDEX idx_memberships_status ON memberships(status);
CREATE INDEX idx_memberships_role ON memberships(role);
CREATE INDEX idx_memberships_invitation_token ON memberships(invitation_token) WHERE invitation_token IS NOT NULL;

-- Comments
COMMENT ON TABLE memberships IS 'Членство пользователей в организациях';
COMMENT ON COLUMN memberships.role IS 'Роль: owner, admin, member, viewer';
COMMENT ON COLUMN memberships.status IS 'Статус: pending, active, disabled, declined';

-- ============================================================================
-- 4. INVITATIONS TABLE (Pending invitations)
-- ============================================================================
CREATE TABLE IF NOT EXISTS invitations (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign key
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Invitee info
    email VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member',

    -- Token
    token VARCHAR(255) UNIQUE NOT NULL,

    -- Inviter
    invited_by_id UUID NOT NULL REFERENCES users(id),

    -- Status
    status VARCHAR(20) DEFAULT 'pending',

    -- Expiration
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    accepted_at TIMESTAMP WITH TIME ZONE,
    declined_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT valid_invitation_role CHECK (role IN ('admin', 'member', 'viewer')),
    CONSTRAINT valid_invitation_status CHECK (status IN ('pending', 'accepted', 'declined', 'expired'))
);

-- Indexes
CREATE INDEX idx_invitations_token ON invitations(token);
CREATE INDEX idx_invitations_email ON invitations(email);
CREATE INDEX idx_invitations_org_id ON invitations(organization_id);
CREATE INDEX idx_invitations_status ON invitations(status);

-- Comments
COMMENT ON TABLE invitations IS 'Приглашения в организацию';
COMMENT ON COLUMN invitations.token IS 'Уникальный токен для принятия приглашения';
COMMENT ON COLUMN invitations.expires_at IS 'Срок действия приглашения';

-- ============================================================================
-- 5. SESSIONS TABLE (JWT refresh tokens)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign key
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Token
    refresh_token VARCHAR(255) UNIQUE NOT NULL,

    -- Metadata
    user_agent TEXT,
    ip_address INET,

    -- Expiration
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    revoked_at TIMESTAMP WITH TIME ZONE
);

-- Indexes
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_refresh_token ON sessions(refresh_token);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);

-- Comments
COMMENT ON TABLE sessions IS 'Сессии пользователей (refresh токены)';
COMMENT ON COLUMN sessions.refresh_token IS 'Refresh токен для обновления access токена';
COMMENT ON COLUMN sessions.ip_address IS 'IP адрес сессии';

-- ============================================================================
-- 6. MODIFY EXISTING DIALOGS TABLE
-- ============================================================================

-- Add columns if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dialogs' AND column_name = 'owner_type'
    ) THEN
        ALTER TABLE dialogs ADD COLUMN owner_type VARCHAR(10) DEFAULT 'user';
        ALTER TABLE dialogs ADD CONSTRAINT valid_dialog_owner_type
            CHECK (owner_type IN ('user', 'organization'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dialogs' AND column_name = 'owner_id'
    ) THEN
        ALTER TABLE dialogs ADD COLUMN owner_id UUID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dialogs' AND column_name = 'created_by'
    ) THEN
        ALTER TABLE dialogs ADD COLUMN created_by UUID REFERENCES users(id);
    END IF;
END $$;

-- Create composite indexes for tenant filtering
CREATE INDEX IF NOT EXISTS idx_dialogs_owner ON dialogs(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_dialogs_created_by ON dialogs(created_by);

-- Comments
COMMENT ON COLUMN dialogs.owner_type IS 'Тип владельца: user или organization';
COMMENT ON COLUMN dialogs.owner_id IS 'ID владельца (user_id или organization_id)';
COMMENT ON COLUMN dialogs.created_by IS 'ID пользователя, создавшего диалог';

-- ============================================================================
-- 7. MIGRATE EXISTING DATA
-- ============================================================================

-- Create a default system user for existing dialogs
INSERT INTO users (id, email, password_hash, full_name, is_active, email_verified)
VALUES (
    '00000000-0000-0000-0000-000000000001'::UUID,
    'system@voicecheck.local',
    '$2b$12$placeholder_hash_for_system_user',
    'System User',
    TRUE,
    TRUE
) ON CONFLICT (id) DO NOTHING;

-- Update existing dialogs to belong to system user
UPDATE dialogs
SET
    owner_type = 'user',
    owner_id = '00000000-0000-0000-0000-000000000001'::UUID,
    created_by = '00000000-0000-0000-0000-000000000001'::UUID
WHERE owner_id IS NULL;

-- ============================================================================
-- 8. ROLES AND PERMISSIONS (For reference)
-- ============================================================================

/*
Role Permissions:

OWNER:
- Everything (create, read, update, delete dialogs)
- Manage organization settings
- Invite/remove members
- Change member roles
- Transfer ownership
- Delete organization

ADMIN:
- Create, read, update, delete dialogs
- Invite/remove members
- Change member roles (except owner)
- View organization settings

MEMBER:
- Create, read, update own dialogs
- Read all dialogs in organization
- Delete own dialogs

VIEWER:
- Read only (all dialogs in organization)
*/

-- ============================================================================
-- 9. USEFUL FUNCTIONS
-- ============================================================================

-- Function: Check if user is member of organization
CREATE OR REPLACE FUNCTION is_organization_member(
    p_user_id UUID,
    p_organization_id UUID
) RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM memberships
        WHERE user_id = p_user_id
          AND organization_id = p_organization_id
          AND status = 'active'
    );
END;
$$ LANGUAGE plpgsql;

-- Function: Get user role in organization
CREATE OR REPLACE FUNCTION get_user_role(
    p_user_id UUID,
    p_organization_id UUID
) RETURNS VARCHAR AS $$
DECLARE
    user_role VARCHAR;
BEGIN
    SELECT role INTO user_role
    FROM memberships
    WHERE user_id = p_user_id
      AND organization_id = p_organization_id
      AND status = 'active';

    RETURN user_role;
END;
$$ LANGUAGE plpgsql;

-- Function: Check if user can access dialog
CREATE OR REPLACE FUNCTION can_access_dialog(
    p_user_id UUID,
    p_dialog_id UUID,
    p_required_permission VARCHAR -- 'read', 'write', 'delete', 'manage'
) RETURNS BOOLEAN AS $$
DECLARE
    dialog_owner_type VARCHAR;
    dialog_owner_id UUID;
    user_role VARCHAR;
BEGIN
    -- Get dialog info
    SELECT owner_type, owner_id INTO dialog_owner_type, dialog_owner_id
    FROM dialogs
    WHERE id = p_dialog_id;

    -- Check if user owns the dialog (personal)
    IF dialog_owner_type = 'user' AND dialog_owner_id = p_user_id THEN
        RETURN TRUE;
    END IF;

    -- Check if dialog belongs to organization
    IF dialog_owner_type = 'organization' THEN
        -- Get user role in organization
        user_role := get_user_role(p_user_id, dialog_owner_id);

        -- Check role permissions
        IF p_required_permission = 'read' THEN
            RETURN user_role IN ('viewer', 'member', 'admin', 'owner');
        ELSIF p_required_permission = 'write' THEN
            RETURN user_role IN ('member', 'admin', 'owner');
        ELSIF p_required_permission = 'delete' THEN
            RETURN user_role IN ('admin', 'owner');
        ELSIF p_required_permission = 'manage' THEN
            RETURN user_role = 'owner';
        END IF;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Function: Get active organizations for user
CREATE OR REPLACE FUNCTION get_user_organizations(p_user_id UUID)
RETURNS TABLE (
    organization_id UUID,
    organization_name VARCHAR,
    organization_slug VARCHAR,
    user_role VARCHAR,
    status VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        o.id,
        o.name,
        o.slug,
        m.role,
        m.status
    FROM organizations o
    JOIN memberships m ON m.organization_id = o.id
    WHERE m.user_id = p_user_id
      AND o.deleted_at IS NULL
    ORDER BY m.created_at;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 10. TRIGGERS
-- ============================================================================

-- Trigger: Update updated_at timestamp on users
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_memberships_updated_at
    BEFORE UPDATE ON memberships
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 11. VIEWS (Useful queries)
-- ============================================================================

-- View: Active members with user details
CREATE OR REPLACE VIEW v_active_members AS
SELECT
    m.id AS membership_id,
    m.organization_id,
    o.name AS organization_name,
    m.user_id,
    u.email AS user_email,
    u.full_name AS user_full_name,
    m.role,
    m.status,
    m.created_at AS joined_at
FROM memberships m
JOIN organizations o ON o.id = m.organization_id
JOIN users u ON u.id = m.user_id
WHERE m.status = 'active'
  AND o.deleted_at IS NULL
  AND u.is_active = TRUE;

COMMENT ON VIEW v_active_members IS 'Активные участники организаций с деталями';

-- View: Organization statistics
CREATE OR REPLACE VIEW v_organization_stats AS
SELECT
    o.id,
    o.name,
    o.slug,
    o.subscription_tier,
    COUNT(DISTINCT m.user_id) FILTER (WHERE m.status = 'active') AS active_members_count,
    COUNT(DISTINCT d.id) AS dialogs_count,
    o.created_at
FROM organizations o
LEFT JOIN memberships m ON m.organization_id = o.id
LEFT JOIN dialogs d ON d.owner_type = 'organization' AND d.owner_id = o.id
WHERE o.deleted_at IS NULL
GROUP BY o.id, o.name, o.slug, o.subscription_tier, o.created_at;

COMMENT ON VIEW v_organization_stats IS 'Статистика организаций';

-- ============================================================================
-- 12. SAMPLE DATA (For testing)
-- ============================================================================

-- Insert test users (REMOVE IN PRODUCTION!)
-- INSERT INTO users (email, password_hash, full_name, is_active, email_verified)
-- VALUES
--     ('owner@example.com', '$2b$12$...', 'Org Owner', TRUE, TRUE),
--     ('admin@example.com', '$2b$12$...', 'Org Admin', TRUE, TRUE),
--     ('member@example.com', '$2b$12$...', 'Org Member', TRUE, TRUE),
--     ('viewer@example.com', '$2b$12$...', 'Org Viewer', TRUE, TRUE);

-- Insert test organization
-- INSERT INTO organizations (name, slug)
-- VALUES ('Test Organization', 'test-org');

-- Insert test memberships
-- INSERT INTO memberships (user_id, organization_id, role, status)
-- SELECT u.id, o.id, 'owner', 'active'
-- FROM users u, organizations o
-- WHERE u.email = 'owner@example.com' AND o.slug = 'test-org';

-- ============================================================================
-- 13. CLEANUP FUNCTIONS (For maintenance)
-- ============================================================================

-- Function: Clean expired invitations
CREATE OR REPLACE FUNCTION clean_expired_invitations()
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM invitations
    WHERE (status = 'pending' AND expires_at < NOW())
       OR (status IN ('accepted', 'declined', 'expired') AND created_at < NOW() - INTERVAL '30 days');

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Clean expired sessions
CREATE OR REPLACE FUNCTION clean_expired_sessions()
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM sessions
    WHERE expires_at < NOW()
       OR (revoked_at IS NOT NULL AND revoked_at < NOW() - INTERVAL '7 days');

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
