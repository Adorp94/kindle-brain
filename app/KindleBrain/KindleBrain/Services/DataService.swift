import Foundation
import SQLite3

/// Direct SQLite access to kindle.db and markdown files.
/// Replaces APIService HTTP calls with local database reads.
actor DataService {
    static let shared = DataService()

    private var kindleDB: OpaquePointer?
    private let dataDir: URL
    private let booksMDDir: URL
    private let coversDir: URL

    /// Resolves the data directory from: UserDefaults > env var > ~/.kindle-brain/
    static func resolveDataDir() -> URL {
        // 1. User-configured path in Settings
        if let saved = UserDefaults.standard.string(forKey: "dataDirectory"), !saved.isEmpty {
            let url = URL(filePath: saved)
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("kindle.db").path) {
                return url
            }
        }
        // 2. Environment variable
        if let env = ProcessInfo.processInfo.environment["KINDLE_BRAIN_DATA"] {
            let url = URL(filePath: env)
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("kindle.db").path) {
                return url
            }
        }
        // 3. Default ~/.kindle-brain/
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".kindle-brain")
    }

    init() {
        dataDir = Self.resolveDataDir()
        booksMDDir = dataDir.appendingPathComponent("books_md")
        coversDir = dataDir.appendingPathComponent("covers")

        // Open database
        let kindlePath = dataDir.appendingPathComponent("kindle.db").path
        if sqlite3_open_v2(kindlePath, &kindleDB, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
            print("[DataService] Failed to open kindle.db at \(kindlePath)")
            kindleDB = nil
        } else {
            print("[DataService] Opened kindle.db at \(kindlePath)")
        }
    }

    deinit {
        sqlite3_close(kindleDB)
    }

    var isDataAvailable: Bool {
        kindleDB != nil
    }

    var dataDirectory: URL { dataDir }

    // MARK: - Books

    func fetchBooks() -> [Book] {
        guard let db = kindleDB else { return [] }
        var books: [Book] = []
        var stmt: OpaquePointer?

        let sql = """
            SELECT b.id, b.title, b.author, b.summary,
                   COUNT(c.id) as highlight_count,
                   SUM(CASE WHEN c.rich_context IS NOT NULL THEN 1 ELSE 0 END) as golden_nuggets,
                   MIN(c.date) as first_highlight,
                   MAX(c.date) as last_highlight
            FROM books b
            LEFT JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
            GROUP BY b.id
            HAVING highlight_count > 0
            ORDER BY highlight_count DESC
        """

        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            while sqlite3_step(stmt) == SQLITE_ROW {
                let id = Int(sqlite3_column_int(stmt, 0))
                let title = String(cString: sqlite3_column_text(stmt, 1))
                let author = columnText(stmt, 2)
                let summary = columnText(stmt, 3)
                let highlightCount = Int(sqlite3_column_int(stmt, 4))
                let goldenNuggets = Int(sqlite3_column_int(stmt, 5))
                let firstHighlight = columnText(stmt, 6).map { String($0.prefix(10)) }
                let lastHighlight = columnText(stmt, 7).map { String($0.prefix(10)) }

                let hasCover = FileManager.default.fileExists(
                    atPath: coversDir.appendingPathComponent("\(id).jpg").path
                )

                books.append(Book(
                    id: id, title: title, author: author, summary: summary,
                    highlightCount: highlightCount, goldenNuggets: goldenNuggets,
                    firstHighlight: firstHighlight,
                    lastHighlight: lastHighlight,
                    hasCover: hasCover
                ))
            }
        }
        sqlite3_finalize(stmt)
        return books
    }

    func fetchBookHighlights(bookId: Int) -> BookHighlightsResponse? {
        guard let db = kindleDB else { return nil }

        // Get book info
        var stmt: OpaquePointer?
        sqlite3_prepare_v2(db, "SELECT title, author, summary FROM books WHERE id = ?", -1, &stmt, nil)
        sqlite3_bind_int(stmt, 1, Int32(bookId))

        guard sqlite3_step(stmt) == SQLITE_ROW else {
            sqlite3_finalize(stmt)
            return nil
        }

        let bookTitle = String(cString: sqlite3_column_text(stmt, 0))
        let bookAuthor = columnText(stmt, 1)
        let bookSummary = columnText(stmt, 2)
        sqlite3_finalize(stmt)

        // Get highlights
        var highlights: [Highlight] = []
        let highlightSQL = """
            SELECT c.id, c.text, c.surrounding_context, c.rich_context,
                   c.page, c.date, c.note_text,
                   ch.title as chapter_title, ch.chapter_number
            FROM clippings c
            LEFT JOIN chapters ch ON c.chapter_id = ch.id
            WHERE c.book_id = ? AND c.type = 'highlight'
            ORDER BY c.position_start
        """

        sqlite3_prepare_v2(db, highlightSQL, -1, &stmt, nil)
        sqlite3_bind_int(stmt, 1, Int32(bookId))

        while sqlite3_step(stmt) == SQLITE_ROW {
            let id = Int(sqlite3_column_int(stmt, 0))
            let text = columnText(stmt, 1) ?? ""
            let surroundingContext = columnText(stmt, 2)
            let richContext = columnText(stmt, 3)
            let page = sqlite3_column_type(stmt, 4) != SQLITE_NULL ? Int(sqlite3_column_int(stmt, 4)) : nil
            let date = columnText(stmt, 5).map { String($0.prefix(10)) }
            let note = columnText(stmt, 6)
            let chapter = columnText(stmt, 7)
            let chapterNumber = sqlite3_column_type(stmt, 8) != SQLITE_NULL ? Int(sqlite3_column_int(stmt, 8)) : nil

            highlights.append(Highlight(
                id: id, text: text, richContext: richContext,
                surroundingContext: surroundingContext,
                page: page, date: date != nil ? String(date!) : nil,
                note: note, chapter: chapter, chapterNumber: chapterNumber
            ))
        }
        sqlite3_finalize(stmt)

        return BookHighlightsResponse(
            book: BookInfo(title: bookTitle, author: bookAuthor, summary: bookSummary),
            highlightCount: highlights.count,
            highlights: highlights
        )
    }

    // MARK: - Highlight Context (for explain feature)

    struct HighlightContext {
        let text: String
        let richContext: String?
        let surroundingContext: String?
        let bookTitle: String
        let author: String?
        let bookSummary: String?
        let chapterTitle: String?
        let chapterSummary: String?
    }

    func getHighlightContext(id: Int) -> HighlightContext? {
        guard let db = kindleDB else { return nil }
        var stmt: OpaquePointer?

        let sql = """
            SELECT c.text, c.rich_context, c.surrounding_context,
                   b.title, b.author, b.summary,
                   ch.title, ch.summary
            FROM clippings c
            JOIN books b ON c.book_id = b.id
            LEFT JOIN chapters ch ON c.chapter_id = ch.id
            WHERE c.id = ?
        """

        sqlite3_prepare_v2(db, sql, -1, &stmt, nil)
        sqlite3_bind_int(stmt, 1, Int32(id))

        guard sqlite3_step(stmt) == SQLITE_ROW else {
            sqlite3_finalize(stmt)
            return nil
        }

        let result = HighlightContext(
            text: columnText(stmt, 0) ?? "",
            richContext: columnText(stmt, 1),
            surroundingContext: columnText(stmt, 2),
            bookTitle: columnText(stmt, 3) ?? "",
            author: columnText(stmt, 4),
            bookSummary: columnText(stmt, 5),
            chapterTitle: columnText(stmt, 6),
            chapterSummary: columnText(stmt, 7)
        )
        sqlite3_finalize(stmt)
        return result
    }

    // MARK: - Stats

    func fetchStats() -> LibraryStats {
        guard let db = kindleDB else {
            return LibraryStats(totalBooks: 0, totalHighlights: 0, goldenNuggets: 0,
                              totalNotes: 0, dateRange: DateRange(first: nil, last: nil), topBooks: [])
        }

        let totalBooks = countQuery(db, "SELECT COUNT(*) FROM books")
        let totalHighlights = countQuery(db, "SELECT COUNT(*) FROM clippings WHERE type = 'highlight'")
        let goldenNuggets = countQuery(db, "SELECT COUNT(*) FROM clippings WHERE rich_context IS NOT NULL")
        let totalNotes = countQuery(db, "SELECT COUNT(*) FROM clippings WHERE type = 'note'")

        // Date range
        var stmt: OpaquePointer?
        var firstDate: String? = nil
        var lastDate: String? = nil
        sqlite3_prepare_v2(db, "SELECT MIN(date), MAX(date) FROM clippings WHERE date IS NOT NULL", -1, &stmt, nil)
        if sqlite3_step(stmt) == SQLITE_ROW {
            firstDate = columnText(stmt, 0).map { String($0.prefix(10)) }
            lastDate = columnText(stmt, 1).map { String($0.prefix(10)) }
        }
        sqlite3_finalize(stmt)

        // Top books
        var topBooks: [TopBook] = []
        let topSQL = """
            SELECT b.title, COUNT(c.id) as cnt
            FROM books b JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
            GROUP BY b.id ORDER BY cnt DESC LIMIT 10
        """
        sqlite3_prepare_v2(db, topSQL, -1, &stmt, nil)
        while sqlite3_step(stmt) == SQLITE_ROW {
            let title = String(cString: sqlite3_column_text(stmt, 0))
            let count = Int(sqlite3_column_int(stmt, 1))
            topBooks.append(TopBook(title: title, highlights: count))
        }
        sqlite3_finalize(stmt)

        return LibraryStats(
            totalBooks: totalBooks, totalHighlights: totalHighlights,
            goldenNuggets: goldenNuggets, totalNotes: totalNotes,
            dateRange: DateRange(first: firstDate, last: lastDate),
            topBooks: topBooks
        )
    }

    // MARK: - File-based Library Tools

    func browseCatalog() -> String {
        let path = booksMDDir.appendingPathComponent("CATALOG.md")
        return (try? String(contentsOf: path, encoding: .utf8)) ?? "CATALOG.md not found at \(path.path)"
    }

    func readBook(title: String) -> String {
        let search = title.lowercased()
        let skipFiles: Set<String> = ["LIBRARY.md", "CATALOG.md"]

        guard let files = try? FileManager.default.contentsOfDirectory(
            at: booksMDDir, includingPropertiesForKeys: nil
        ) else {
            return "Books directory not found at \(booksMDDir.path)"
        }

        let matches = files.filter { url in
            url.pathExtension == "md"
            && !skipFiles.contains(url.lastPathComponent)
            && url.deletingPathExtension().lastPathComponent.lowercased().contains(search)
        }

        if matches.isEmpty {
            let available = files
                .filter { $0.pathExtension == "md" && !skipFiles.contains($0.lastPathComponent) }
                .map { $0.deletingPathExtension().lastPathComponent }
                .sorted()
                .prefix(20)
            return "No book found matching '\(title)'. Available: \(available.joined(separator: ", "))"
        }

        if matches.count > 1 {
            return "Multiple matches: \(matches.map { $0.deletingPathExtension().lastPathComponent }.joined(separator: ", ")). Be more specific."
        }

        var content = (try? String(contentsOf: matches[0], encoding: .utf8)) ?? ""

        // Strip golden nuggets for lighter response
        if let regex = try? NSRegularExpression(
            pattern: "<details>\\s*<summary>Golden Nugget \\(context\\)</summary>\\s*[\\s\\S]*?\\s*</details>\\s*",
            options: []
        ) {
            content = regex.stringByReplacingMatches(
                in: content, range: NSRange(content.startIndex..., in: content), withTemplate: ""
            )
        }

        return content
    }

    func coverURL(bookId: Int) -> URL? {
        let path = coversDir.appendingPathComponent("\(bookId).jpg")
        return FileManager.default.fileExists(atPath: path.path) ? path : nil
    }

    // MARK: - Helpers

    private func columnText(_ stmt: OpaquePointer?, _ index: Int32) -> String? {
        guard let ptr = sqlite3_column_text(stmt, index) else { return nil }
        return String(cString: ptr)
    }

    private func countQuery(_ db: OpaquePointer?, _ sql: String) -> Int {
        var stmt: OpaquePointer?
        sqlite3_prepare_v2(db, sql, -1, &stmt, nil)
        defer { sqlite3_finalize(stmt) }
        return sqlite3_step(stmt) == SQLITE_ROW ? Int(sqlite3_column_int(stmt, 0)) : 0
    }
}
