import Foundation
import SQLite3

/// Persists chat conversations to SQLite for history.
actor ChatStore {
    static let shared = ChatStore()

    private var db: OpaquePointer?
    private let dbPath: String

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("KindleBrain", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        dbPath = dir.appendingPathComponent("chats.db").path

        // Open DB inline in init (db is a stored property, accessible here)
        if sqlite3_open(dbPath, &db) != SQLITE_OK {
            print("[ChatStore] Failed to open DB at \(dbPath)")
        }

        // Create tables inline
        let sql = """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            sources_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        """
        sqlite3_exec(db, sql, nil, nil, nil)
    }

    private func createTables() {
        let sql = """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            sources_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
        """
        sqlite3_exec(db, sql, nil, nil, nil)
    }

    // MARK: - Conversations

    func listConversations() -> [Conversation] {
        var results: [Conversation] = []
        var stmt: OpaquePointer?
        let sql = "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            while sqlite3_step(stmt) == SQLITE_ROW {
                let id = String(cString: sqlite3_column_text(stmt, 0))
                let title = String(cString: sqlite3_column_text(stmt, 1))
                let created = String(cString: sqlite3_column_text(stmt, 2))
                let updated = String(cString: sqlite3_column_text(stmt, 3))
                results.append(Conversation(
                    id: id, title: title,
                    createdAt: ISO8601DateFormatter().date(from: created) ?? .now,
                    updatedAt: ISO8601DateFormatter().date(from: updated) ?? .now
                ))
            }
        }
        sqlite3_finalize(stmt)
        return results
    }

    func createConversation(id: String, title: String) {
        var stmt: OpaquePointer?
        let now = ISO8601DateFormatter().string(from: .now)
        let sql = "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)"

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, (id as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (title as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 3, (now as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 4, (now as NSString).utf8String, -1, nil)
            sqlite3_step(stmt)
        }
        sqlite3_finalize(stmt)
    }

    func updateConversation(id: String, title: String) {
        var stmt: OpaquePointer?
        let now = ISO8601DateFormatter().string(from: .now)
        let sql = "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?"

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, (title as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (now as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 3, (id as NSString).utf8String, -1, nil)
            sqlite3_step(stmt)
        }
        sqlite3_finalize(stmt)
    }

    func deleteConversation(id: String) {
        sqlite3_exec(db, "DELETE FROM messages WHERE conversation_id = '\(id)'", nil, nil, nil)
        sqlite3_exec(db, "DELETE FROM conversations WHERE id = '\(id)'", nil, nil, nil)
    }

    // MARK: - Messages

    func saveMessage(_ msg: ChatMessage, conversationId: String) {
        var stmt: OpaquePointer?
        let sql = "INSERT OR REPLACE INTO messages (id, conversation_id, role, text, sources_json, created_at) VALUES (?, ?, ?, ?, ?, ?)"

        var sourcesJson: String? = nil
        if !msg.sources.isEmpty {
            if let data = try? JSONEncoder().encode(msg.sources) {
                sourcesJson = String(data: data, encoding: .utf8)
            }
        }

        let now = ISO8601DateFormatter().string(from: msg.timestamp)

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, (msg.id.uuidString as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (conversationId as NSString).utf8String, -1, nil)
            let roleStr: NSString = msg.role == .user ? "user" : "assistant"
            sqlite3_bind_text(stmt, 3, roleStr.utf8String, -1, nil)
            sqlite3_bind_text(stmt, 4, (msg.text as NSString).utf8String, -1, nil)
            if let sj = sourcesJson {
                sqlite3_bind_text(stmt, 5, (sj as NSString).utf8String, -1, nil)
            } else {
                sqlite3_bind_null(stmt, 5)
            }
            sqlite3_bind_text(stmt, 6, (now as NSString).utf8String, -1, nil)
            sqlite3_step(stmt)
        }
        sqlite3_finalize(stmt)

        // Touch conversation updated_at
        let touchSql = "UPDATE conversations SET updated_at = '\(ISO8601DateFormatter().string(from: .now))' WHERE id = '\(conversationId)'"
        sqlite3_exec(db, touchSql, nil, nil, nil)
    }

    func loadMessages(conversationId: String) -> [ChatMessage] {
        var results: [ChatMessage] = []
        var stmt: OpaquePointer?
        let sql = "SELECT id, role, text, sources_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC"

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, (conversationId as NSString).utf8String, -1, nil)

            while sqlite3_step(stmt) == SQLITE_ROW {
                let idStr = String(cString: sqlite3_column_text(stmt, 0))
                let roleStr = String(cString: sqlite3_column_text(stmt, 1))
                let text = String(cString: sqlite3_column_text(stmt, 2))
                let created = String(cString: sqlite3_column_text(stmt, 4))

                var sources: [ChatSource] = []
                if sqlite3_column_type(stmt, 3) != SQLITE_NULL {
                    let sourcesStr = String(cString: sqlite3_column_text(stmt, 3))
                    if let data = sourcesStr.data(using: .utf8) {
                        sources = (try? JSONDecoder().decode([ChatSource].self, from: data)) ?? []
                    }
                }

                let msg = ChatMessage(
                    id: UUID(uuidString: idStr) ?? UUID(),
                    role: roleStr == "user" ? .user : .assistant,
                    text: text,
                    sources: sources,
                    timestamp: ISO8601DateFormatter().date(from: created) ?? .now
                )
                results.append(msg)
            }
        }
        sqlite3_finalize(stmt)
        return results
    }
}

struct Conversation: Identifiable {
    let id: String
    let title: String
    let createdAt: Date
    let updatedAt: Date
}
