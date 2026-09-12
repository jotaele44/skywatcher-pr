import CryptoKit
import Foundation
import SQLite3

struct MobileImportManifest: Equatable {
    let generationID: String
    let sourceSHA256: String
    let rawCount: Int
    let retainedCount: Int
    let excludedCount: Int
    let unresolvedCount: Int
    let stableIDCount: Int
    let state: String
}

struct MobileBackupReceipt: Equatable {
    let backupID: String
    let databaseSHA256: String
    let byteCount: Int64
    let createdAt: String
}

enum MobilePersistenceError: Error, Equatable {
    case invalidSHA256
    case arithmeticMismatch
    case duplicateStableID
    case invalidStableID
    case invalidCount
    case database(String)
    case inactiveGeneration
    case integrityFailure
    case backupHashMismatch
}

/// Device-local persistence only. This store owns workspace/import/annotation/
/// backup state and deliberately does not duplicate producer flight, aircraft,
/// RLSM, or federation-domain tables.
final class MobilePersistenceStore {
    private static let migrationLedgerDDL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
      applied_at TEXT NOT NULL
    )
    """

    private static let migration1 = """
    CREATE TABLE IF NOT EXISTS workspace_state (
      key TEXT PRIMARY KEY,
      value_json BLOB NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS import_manifest (
      generation_id TEXT PRIMARY KEY,
      source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
      raw_count INTEGER NOT NULL CHECK(raw_count >= 0),
      retained_count INTEGER NOT NULL CHECK(retained_count >= 0),
      excluded_count INTEGER NOT NULL CHECK(excluded_count >= 0),
      unresolved_count INTEGER NOT NULL CHECK(unresolved_count >= 0),
      stable_id_count INTEGER NOT NULL CHECK(stable_id_count >= 0),
      state TEXT NOT NULL CHECK(state IN ('STAGED','ACTIVE','RETIRED','REJECTED')),
      created_at TEXT NOT NULL,
      activated_at TEXT,
      CHECK(raw_count = retained_count + excluded_count + unresolved_count),
      CHECK(stable_id_count = retained_count)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_import
      ON import_manifest(state) WHERE state = 'ACTIVE';
    CREATE TABLE IF NOT EXISTS import_record_ref (
      generation_id TEXT NOT NULL,
      stable_id TEXT NOT NULL CHECK(length(trim(stable_id)) > 0),
      canonical_ref TEXT,
      PRIMARY KEY(generation_id, stable_id),
      FOREIGN KEY(generation_id) REFERENCES import_manifest(generation_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS import_receipt (
      receipt_id TEXT PRIMARY KEY,
      generation_id TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('PASS','FAIL')),
      detail TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(generation_id) REFERENCES import_manifest(generation_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS local_annotation (
      annotation_id TEXT PRIMARY KEY,
      canonical_ref TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attachment_manifest (
      attachment_id TEXT PRIMARY KEY,
      sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
      byte_count INTEGER NOT NULL CHECK(byte_count >= 0),
      relative_path TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backup_receipt (
      backup_id TEXT PRIMARY KEY,
      database_sha256 TEXT NOT NULL CHECK(length(database_sha256) = 64),
      byte_count INTEGER NOT NULL CHECK(byte_count >= 0),
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sync_state (
      authority TEXT PRIMARY KEY,
      cursor TEXT,
      last_success_at TEXT,
      state TEXT NOT NULL
    );
    """

    private static let migrations: [(version: Int, name: String, sql: String)] = [
        (1, "device_local_foundation", migration1)
    ]

    private let databaseURL: URL
    private var db: OpaquePointer?
    private let iso8601 = ISO8601DateFormatter()

    init(databaseURL: URL) throws {
        self.databaseURL = databaseURL
        try FileManager.default.createDirectory(
            at: databaseURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try open()
        try configure()
        try migrate()
    }

    deinit {
        if let db { sqlite3_close(db) }
    }

    func close() throws {
        guard let db else { return }
        let rc = sqlite3_close(db)
        guard rc == SQLITE_OK else { throw sqlError("close", code: rc) }
        self.db = nil
    }

    func schemaVersion() throws -> Int {
        try scalarInt("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    }

    func setWorkspaceValue(key: String, value: Data) throws {
        let statement = try prepare("""
        INSERT INTO workspace_state(key, value_json, updated_at) VALUES(?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
        """)
        defer { sqlite3_finalize(statement) }
        try bindText(statement, index: 1, value: key)
        value.withUnsafeBytes { raw in
            _ = sqlite3_bind_blob(statement, 2, raw.baseAddress, Int32(raw.count), Self.transient)
        }
        try bindText(statement, index: 3, value: now())
        try stepDone(statement)
    }

    func workspaceValue(key: String) throws -> Data? {
        let statement = try prepare("SELECT value_json FROM workspace_state WHERE key = ?")
        defer { sqlite3_finalize(statement) }
        try bindText(statement, index: 1, value: key)
        let rc = sqlite3_step(statement)
        if rc == SQLITE_DONE { return nil }
        guard rc == SQLITE_ROW else { throw sqlError("workspace read", code: rc) }
        let count = Int(sqlite3_column_bytes(statement, 0))
        guard count > 0, let ptr = sqlite3_column_blob(statement, 0) else { return Data() }
        return Data(bytes: ptr, count: count)
    }

    @discardableResult
    func stageImport(
        generationID: String,
        sourceSHA256: String,
        rawCount: Int,
        retainedCount: Int,
        excludedCount: Int,
        unresolvedCount: Int,
        stableIDs: [String]
    ) throws -> MobileImportManifest {
        guard Self.isSHA256(sourceSHA256) else { throw MobilePersistenceError.invalidSHA256 }
        guard rawCount >= 0, retainedCount >= 0, excludedCount >= 0, unresolvedCount >= 0 else {
            throw MobilePersistenceError.invalidCount
        }
        guard rawCount == retainedCount + excludedCount + unresolvedCount else {
            throw MobilePersistenceError.arithmeticMismatch
        }
        guard stableIDs.count == retainedCount else { throw MobilePersistenceError.invalidCount }
        guard stableIDs.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
            throw MobilePersistenceError.invalidStableID
        }
        guard Set(stableIDs).count == stableIDs.count else {
            throw MobilePersistenceError.duplicateStableID
        }

        try transaction {
            let statement = try prepare("""
            INSERT INTO import_manifest(
              generation_id, source_sha256, raw_count, retained_count,
              excluded_count, unresolved_count, stable_id_count, state, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 'STAGED', ?)
            """)
            defer { sqlite3_finalize(statement) }
            try bindText(statement, index: 1, value: generationID)
            try bindText(statement, index: 2, value: sourceSHA256.lowercased())
            sqlite3_bind_int64(statement, 3, sqlite3_int64(rawCount))
            sqlite3_bind_int64(statement, 4, sqlite3_int64(retainedCount))
            sqlite3_bind_int64(statement, 5, sqlite3_int64(excludedCount))
            sqlite3_bind_int64(statement, 6, sqlite3_int64(unresolvedCount))
            sqlite3_bind_int64(statement, 7, sqlite3_int64(stableIDs.count))
            try bindText(statement, index: 8, value: now())
            try stepDone(statement)

            for stableID in stableIDs {
                let ref = try prepare("INSERT INTO import_record_ref(generation_id, stable_id) VALUES(?, ?)")
                defer { sqlite3_finalize(ref) }
                try bindText(ref, index: 1, value: generationID)
                try bindText(ref, index: 2, value: stableID)
                try stepDone(ref)
            }
        }

        return MobileImportManifest(
            generationID: generationID,
            sourceSHA256: sourceSHA256.lowercased(),
            rawCount: rawCount,
            retainedCount: retainedCount,
            excludedCount: excludedCount,
            unresolvedCount: unresolvedCount,
            stableIDCount: stableIDs.count,
            state: "STAGED"
        )
    }

    func activateGeneration(_ generationID: String) throws {
        try transaction {
            let expected = try scalarInt(
                "SELECT stable_id_count FROM import_manifest WHERE generation_id = ? AND state = 'STAGED'",
                textArgument: generationID
            )
            guard expected >= 0 else { throw MobilePersistenceError.inactiveGeneration }
            let actual = try scalarInt(
                "SELECT COUNT(*) FROM import_record_ref WHERE generation_id = ?",
                textArgument: generationID
            )
            guard expected == actual else { throw MobilePersistenceError.integrityFailure }

            try execute("UPDATE import_manifest SET state = 'RETIRED' WHERE state = 'ACTIVE'")
            let update = try prepare(
                "UPDATE import_manifest SET state = 'ACTIVE', activated_at = ? WHERE generation_id = ? AND state = 'STAGED'"
            )
            defer { sqlite3_finalize(update) }
            try bindText(update, index: 1, value: now())
            try bindText(update, index: 2, value: generationID)
            try stepDone(update)
            guard sqlite3_changes(db) == 1 else { throw MobilePersistenceError.inactiveGeneration }
        }
    }

    func activeGenerationID() throws -> String? {
        let statement = try prepare("SELECT generation_id FROM import_manifest WHERE state = 'ACTIVE'")
        defer { sqlite3_finalize(statement) }
        let rc = sqlite3_step(statement)
        if rc == SQLITE_DONE { return nil }
        guard rc == SQLITE_ROW, let text = sqlite3_column_text(statement, 0) else {
            throw sqlError("active generation", code: rc)
        }
        return String(cString: text)
    }

    func importState(generationID: String) throws -> String? {
        let statement = try prepare("SELECT state FROM import_manifest WHERE generation_id = ?")
        defer { sqlite3_finalize(statement) }
        try bindText(statement, index: 1, value: generationID)
        let rc = sqlite3_step(statement)
        if rc == SQLITE_DONE { return nil }
        guard rc == SQLITE_ROW, let text = sqlite3_column_text(statement, 0) else {
            throw sqlError("import state", code: rc)
        }
        return String(cString: text)
    }

    func createBackup(at backupURL: URL) throws -> MobileBackupReceipt {
        guard let db else { throw MobilePersistenceError.database("database closed") }
        try execute("PRAGMA wal_checkpoint(FULL)")
        Self.removeDatabaseFiles(at: backupURL)
        try FileManager.default.createDirectory(
            at: backupURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        var destination: OpaquePointer?
        let openRC = sqlite3_open_v2(backupURL.path, &destination, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, nil)
        guard openRC == SQLITE_OK, let destination else {
            if let destination { sqlite3_close(destination) }
            throw MobilePersistenceError.database("backup destination open failed: \(openRC)")
        }
        defer { sqlite3_close(destination) }

        guard let backup = sqlite3_backup_init(destination, "main", db, "main") else {
            throw MobilePersistenceError.database("backup init failed")
        }
        let stepRC = sqlite3_backup_step(backup, -1)
        let finishRC = sqlite3_backup_finish(backup)
        guard stepRC == SQLITE_DONE, finishRC == SQLITE_OK else {
            throw MobilePersistenceError.database("backup failed: step=\(stepRC) finish=\(finishRC)")
        }

        let receipt = MobileBackupReceipt(
            backupID: UUID().uuidString.lowercased(),
            databaseSHA256: try Self.fileSHA256(backupURL),
            byteCount: try Self.fileSize(backupURL),
            createdAt: now()
        )
        let statement = try prepare(
            "INSERT INTO backup_receipt(backup_id, database_sha256, byte_count, created_at) VALUES(?, ?, ?, ?)"
        )
        defer { sqlite3_finalize(statement) }
        try bindText(statement, index: 1, value: receipt.backupID)
        try bindText(statement, index: 2, value: receipt.databaseSHA256)
        sqlite3_bind_int64(statement, 3, sqlite3_int64(receipt.byteCount))
        try bindText(statement, index: 4, value: receipt.createdAt)
        try stepDone(statement)
        return receipt
    }

    static func restoreBackup(from backupURL: URL, expectedSHA256: String, to databaseURL: URL) throws {
        guard isSHA256(expectedSHA256) else { throw MobilePersistenceError.invalidSHA256 }
        guard try fileSHA256(backupURL) == expectedSHA256.lowercased() else {
            throw MobilePersistenceError.backupHashMismatch
        }

        let fm = FileManager.default
        let rollbackURL = databaseURL.appendingPathExtension("pre-restore")
        removeDatabaseFiles(at: rollbackURL)
        let hadCurrent = fm.fileExists(atPath: databaseURL.path)
        if hadCurrent { try fm.copyItem(at: databaseURL, to: rollbackURL) }

        do {
            removeDatabaseFiles(at: databaseURL)
            try fm.copyItem(at: backupURL, to: databaseURL)
            var checkDB: OpaquePointer?
            let rc = sqlite3_open_v2(databaseURL.path, &checkDB, SQLITE_OPEN_READONLY, nil)
            guard rc == SQLITE_OK, let checkDB else { throw MobilePersistenceError.integrityFailure }
            defer { sqlite3_close(checkDB) }
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(checkDB, "PRAGMA integrity_check", -1, &statement, nil) == SQLITE_OK,
                  let statement else { throw MobilePersistenceError.integrityFailure }
            defer { sqlite3_finalize(statement) }
            guard sqlite3_step(statement) == SQLITE_ROW,
                  let text = sqlite3_column_text(statement, 0),
                  String(cString: text) == "ok" else { throw MobilePersistenceError.integrityFailure }
            removeDatabaseFiles(at: rollbackURL)
        } catch {
            removeDatabaseFiles(at: databaseURL)
            if hadCurrent { try? fm.moveItem(at: rollbackURL, to: databaseURL) }
            throw error
        }
    }

    private func open() throws {
        var handle: OpaquePointer?
        let rc = sqlite3_open_v2(
            databaseURL.path,
            &handle,
            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
            nil
        )
        guard rc == SQLITE_OK, let handle else {
            if let handle { sqlite3_close(handle) }
            throw MobilePersistenceError.database("open failed: \(rc)")
        }
        db = handle
    }

    private func configure() throws {
        try execute("PRAGMA foreign_keys = ON")
        try execute("PRAGMA journal_mode = WAL")
        try execute("PRAGMA synchronous = FULL")
    }

    private func migrate() throws {
        try execute(Self.migrationLedgerDDL)
        let current = try schemaVersion()
        for migration in Self.migrations where migration.version > current {
            let hash = Self.sha256(Data(migration.sql.utf8))
            try transaction {
                try execute(migration.sql)
                let statement = try prepare(
                    "INSERT INTO schema_migrations(version, name, sha256, applied_at) VALUES(?, ?, ?, ?)"
                )
                defer { sqlite3_finalize(statement) }
                sqlite3_bind_int64(statement, 1, sqlite3_int64(migration.version))
                try bindText(statement, index: 2, value: migration.name)
                try bindText(statement, index: 3, value: hash)
                try bindText(statement, index: 4, value: now())
                try stepDone(statement)
            }
        }
    }

    private func transaction(_ body: () throws -> Void) throws {
        try execute("BEGIN IMMEDIATE")
        do {
            try body()
            try execute("COMMIT")
        } catch {
            try? execute("ROLLBACK")
            throw error
        }
    }

    private func prepare(_ sql: String) throws -> OpaquePointer {
        guard let db else { throw MobilePersistenceError.database("database closed") }
        var statement: OpaquePointer?
        let rc = sqlite3_prepare_v2(db, sql, -1, &statement, nil)
        guard rc == SQLITE_OK, let statement else { throw sqlError("prepare", code: rc) }
        return statement
    }

    private func execute(_ sql: String) throws {
        guard let db else { throw MobilePersistenceError.database("database closed") }
        var message: UnsafeMutablePointer<Int8>?
        let rc = sqlite3_exec(db, sql, nil, nil, &message)
        if rc != SQLITE_OK {
            let detail = message.map { String(cString: $0) } ?? "unknown sqlite error"
            sqlite3_free(message)
            throw MobilePersistenceError.database("\(detail) [\(rc)]")
        }
    }

    private func scalarInt(_ sql: String, textArgument: String? = nil) throws -> Int {
        let statement = try prepare(sql)
        defer { sqlite3_finalize(statement) }
        if let textArgument { try bindText(statement, index: 1, value: textArgument) }
        let rc = sqlite3_step(statement)
        if rc == SQLITE_DONE, textArgument != nil { return -1 }
        guard rc == SQLITE_ROW else { throw sqlError("scalar", code: rc) }
        return Int(sqlite3_column_int64(statement, 0))
    }

    private func bindText(_ statement: OpaquePointer, index: Int32, value: String) throws {
        let rc = sqlite3_bind_text(statement, index, value, -1, Self.transient)
        guard rc == SQLITE_OK else { throw sqlError("bind text", code: rc) }
    }

    private func stepDone(_ statement: OpaquePointer) throws {
        let rc = sqlite3_step(statement)
        guard rc == SQLITE_DONE else { throw sqlError("step", code: rc) }
    }

    private func sqlError(_ operation: String, code: Int32) -> MobilePersistenceError {
        let detail = db.map { String(cString: sqlite3_errmsg($0)) } ?? "database closed"
        return .database("\(operation): \(detail) [\(code)]")
    }

    private func now() -> String { iso8601.string(from: Date()) }

    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private static func isSHA256(_ value: String) -> Bool {
        guard value.utf8.count == 64 else { return false }
        return value.utf8.allSatisfy { byte in
            (48...57).contains(byte) || (65...70).contains(byte) || (97...102).contains(byte)
        }
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func fileSHA256(_ url: URL) throws -> String {
        sha256(try Data(contentsOf: url, options: .mappedIfSafe))
    }

    private static func fileSize(_ url: URL) throws -> Int64 {
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        return (attrs[.size] as? NSNumber)?.int64Value ?? 0
    }

    private static func removeDatabaseFiles(at url: URL) {
        let fm = FileManager.default
        try? fm.removeItem(at: url)
        try? fm.removeItem(atPath: url.path + "-wal")
        try? fm.removeItem(atPath: url.path + "-shm")
    }
}
