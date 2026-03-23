import Foundation

struct Book: Identifiable, Codable, Hashable {
    let id: Int
    let title: String
    let author: String?
    let summary: String?
    let highlightCount: Int
    let goldenNuggets: Int
    let firstHighlight: String?
    let lastHighlight: String?
    let hasCover: Bool?

    enum CodingKeys: String, CodingKey {
        case id, title, author, summary
        case highlightCount = "highlight_count"
        case goldenNuggets = "golden_nuggets"
        case firstHighlight = "first_highlight"
        case lastHighlight = "last_highlight"
        case hasCover = "has_cover"
    }

    var coverURL: URL? {
        guard hasCover == true else { return nil }
        return URL(string: "http://127.0.0.1:8765/covers/\(id).jpg")
    }
}

struct Highlight: Identifiable, Codable {
    let id: Int
    let text: String
    let richContext: String?
    let surroundingContext: String?
    let page: Int?
    let date: String?
    let note: String?
    let chapter: String?
    let chapterNumber: Int?

    enum CodingKeys: String, CodingKey {
        case id, text, page, date, note, chapter
        case richContext = "rich_context"
        case surroundingContext = "surrounding_context"
        case chapterNumber = "chapter_number"
    }
}

struct BookHighlightsResponse: Codable {
    let book: BookInfo
    let highlightCount: Int
    let highlights: [Highlight]

    enum CodingKeys: String, CodingKey {
        case book, highlights
        case highlightCount = "highlight_count"
    }
}

struct BookInfo: Codable {
    let title: String
    let author: String?
    let summary: String?
}

struct ChatResponse: Codable {
    let response: String
    let sources: [ChatSource]
}

struct ChatSource: Identifiable, Codable {
    var id: String { "\(bookTitle)-\(page ?? 0)-\(highlight.prefix(20))" }
    let bookTitle: String
    let author: String?
    let page: Int?
    let highlight: String
    let score: Double?

    enum CodingKeys: String, CodingKey {
        case author, page, highlight, score
        case bookTitle = "book_title"
    }
}

struct HighlightExplanation: Codable {
    let highlightId: Int
    let highlight: String
    let bookTitle: String
    let chapter: String?
    let explanation: String

    enum CodingKeys: String, CodingKey {
        case highlight, chapter, explanation
        case highlightId = "highlight_id"
        case bookTitle = "book_title"
    }
}

struct SearchResult: Identifiable, Codable {
    var id: String { "\(bookTitle)-\(page ?? 0)-\(highlight.prefix(30))" }
    let score: Double
    let highlight: String
    let bookTitle: String
    let author: String?
    let page: Int?
    let chapter: String?
    let date: String?

    enum CodingKeys: String, CodingKey {
        case score, highlight, author, page, chapter, date
        case bookTitle = "book_title"
    }
}

struct LibraryStats: Codable {
    let totalBooks: Int
    let totalHighlights: Int
    let goldenNuggets: Int
    let totalNotes: Int
    let dateRange: DateRange
    let topBooks: [TopBook]

    enum CodingKeys: String, CodingKey {
        case totalBooks = "total_books"
        case totalHighlights = "total_highlights"
        case goldenNuggets = "golden_nuggets"
        case totalNotes = "total_notes"
        case dateRange = "date_range"
        case topBooks = "top_books"
    }
}

struct DateRange: Codable {
    let first: String?
    let last: String?
}

struct TopBook: Codable, Identifiable {
    var id: String { title }
    let title: String
    let highlights: Int
}

struct ChatMessage: Identifiable {
    let id: UUID
    let role: Role
    var text: String
    var sources: [ChatSource]
    let timestamp: Date

    enum Role {
        case user, assistant
    }

    init(role: Role, text: String, sources: [ChatSource] = [], timestamp: Date = .now) {
        self.id = UUID()
        self.role = role
        self.text = text
        self.sources = sources
        self.timestamp = timestamp
    }

    init(id: UUID, role: Role, text: String, sources: [ChatSource] = [], timestamp: Date = .now) {
        self.id = id
        self.role = role
        self.text = text
        self.sources = sources
        self.timestamp = timestamp
    }
}

// MARK: - Memory

struct MemoryResponse: Codable {
    let memories: [UserMemory]
    let recentConversations: [ConversationSummary]
    let topInterests: [ReadingInterest]

    enum CodingKeys: String, CodingKey {
        case memories
        case recentConversations = "recent_conversations"
        case topInterests = "top_interests"
    }
}

struct UserMemory: Identifiable, Codable {
    let id: Int
    let fact: String
    let category: String
    let confidence: Double
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, fact, category, confidence
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct ConversationSummary: Identifiable, Codable {
    var id: String { conversationId }
    let conversationId: String
    let userQuery: String
    let summary: String
    let topics: String?
    let booksMentioned: String?
    let language: String?
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case userQuery = "user_query"
        case summary, topics, language
        case booksMentioned = "books_mentioned"
        case createdAt = "created_at"
    }
}

struct ReadingInterest: Identifiable, Codable {
    var id: String { topic }
    let topic: String
    let queryCount: Int
    let lastQuery: String?
    let booksRelated: String?
    let lastAsked: String

    enum CodingKeys: String, CodingKey {
        case topic
        case queryCount = "query_count"
        case lastQuery = "last_query"
        case booksRelated = "books_related"
        case lastAsked = "last_asked"
    }
}
