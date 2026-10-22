-- The main database (legal_docs) is created by POSTGRES_DB.
-- Tests get their own database so running pytest never touches dev data.
CREATE DATABASE legal_docs_test OWNER legal;
