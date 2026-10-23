"""Migração aditiva, idempotente e executada sob o lock de init_db."""
from sqlalchemy import text


async def migrate_legal(conn):
    from app.models.legal import (LegalConfig, LegalDocument, LegalAcceptance,
                                  LegalCampaign, LegalInvitation, LegalAudit)
    for model in (LegalConfig, LegalDocument, LegalAcceptance, LegalCampaign, LegalInvitation, LegalAudit):
        await conn.run_sync(lambda sync, table=model.__table__: table.create(sync, checkfirst=True))
    await conn.execute(text("""
        INSERT INTO legal_config (id, require_on_redemption, voluntary_enabled,
                                  communications_enabled, token_days)
        VALUES (1, FALSE, FALSE, FALSE, 30) ON CONFLICT (id) DO NOTHING
    """))
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION legal_preserve_document() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Documentos legais nao podem ser excluidos';
            END IF;
            IF OLD.published_at IS NOT NULL THEN
                IF NEW.status NOT IN ('published', 'archived')
                   OR (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
                   OR (OLD.status = 'archived' AND NEW.status <> 'archived') THEN
                    RAISE EXCEPTION 'Versao legal publicada e imutavel';
                END IF;
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """))
    await conn.execute(text("DROP TRIGGER IF EXISTS legal_document_immutable ON legal_documents"))
    await conn.execute(text("""
        CREATE TRIGGER legal_document_immutable BEFORE UPDATE OR DELETE ON legal_documents
        FOR EACH ROW EXECUTE FUNCTION legal_preserve_document()
    """))
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION legal_preserve_evidence() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Evidencia legal e imutavel'; END; $$ LANGUAGE plpgsql
    """))
    for table in ("legal_acceptances", "legal_audit"):
        await conn.execute(text(f"DROP TRIGGER IF EXISTS legal_evidence_immutable ON {table}"))
        await conn.execute(text(f"""
            CREATE TRIGGER legal_evidence_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION legal_preserve_evidence()
        """))
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION legal_validate_acceptance() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM legal_documents
                WHERE id=NEW.terms_id AND kind='terms' AND published_at IS NOT NULL
                  AND status IN ('published', 'archived') AND sha256=NEW.terms_hash)
            OR NOT EXISTS (SELECT 1 FROM legal_documents
                WHERE id=NEW.privacy_id AND kind='privacy' AND published_at IS NOT NULL
                  AND status IN ('published', 'archived') AND sha256=NEW.privacy_hash) THEN
                RAISE EXCEPTION 'Aceite exige documentos publicados e hashes correspondentes';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """))
    await conn.execute(text("DROP TRIGGER IF EXISTS legal_acceptance_valid ON legal_acceptances"))
    await conn.execute(text("""
        CREATE TRIGGER legal_acceptance_valid BEFORE INSERT ON legal_acceptances
        FOR EACH ROW EXECUTE FUNCTION legal_validate_acceptance()
    """))
