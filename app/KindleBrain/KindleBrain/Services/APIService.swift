import Foundation

actor APIService {
    static let shared = APIService()
    private let baseURL = "http://127.0.0.1:8765"
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    // MARK: - Books

    func fetchBooks() async throws -> [Book] {
        let url = URL(string: "\(baseURL)/books")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode([Book].self, from: data)
    }

    func fetchBookHighlights(bookId: Int) async throws -> BookHighlightsResponse {
        let url = URL(string: "\(baseURL)/books/\(bookId)/highlights")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode(BookHighlightsResponse.self, from: data)
    }

    // MARK: - Search

    func search(query: String, top: Int = 10, book: String? = nil) async throws -> [SearchResult] {
        var components = URLComponents(string: "\(baseURL)/search")!
        components.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "top", value: String(top)),
        ]
        if let book {
            components.queryItems?.append(URLQueryItem(name: "book", value: book))
        }
        let (data, _) = try await URLSession.shared.data(from: components.url!)
        return try decoder.decode([SearchResult].self, from: data)
    }

    // MARK: - Chat (non-streaming)

    func chat(message: String) async throws -> ChatResponse {
        let url = URL(string: "\(baseURL)/chat")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["message": message])

        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(ChatResponse.self, from: data)
    }

    // MARK: - Chat (streaming SSE)

    /// Simple SSE parser: processes each line as it arrives.
    /// Tokens have newlines encoded as literal \n — decoded here.
    func chatStream(message: String, conversationId: String? = nil) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let url = URL(string: "\(baseURL)/chat/stream")!
                    var request = URLRequest(url: url)
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    var body: [String: String] = ["message": message]
                    if let convId = conversationId {
                        body["conversation_id"] = convId
                    }
                    request.httpBody = try JSONEncoder().encode(body)

                    let (bytes, _) = try await URLSession.shared.bytes(for: request)
                    var currentEvent = ""

                    for try await line in bytes.lines {
                        if line.hasPrefix("event:") {
                            currentEvent = line.dropFirst(6).trimmingCharacters(in: .whitespaces)
                        } else if line.hasPrefix("data:") {
                            let rawData = String(line.dropFirst(5))
                            // Trim the leading space that SSE adds after "data:"
                            let data = rawData.hasPrefix(" ") ? String(rawData.dropFirst()) : rawData

                            switch currentEvent {
                            case "sources":
                                if let jsonData = data.data(using: .utf8),
                                   let sources = try? JSONDecoder().decode([ChatSource].self, from: jsonData) {
                                    continuation.yield(.sources(sources))
                                }
                            case "thinking":
                                // Decode escaped newlines
                                let decoded = data.replacingOccurrences(of: "\\n", with: "\n")
                                continuation.yield(.thinking(decoded))
                            case "token":
                                // Decode escaped newlines
                                let decoded = data.replacingOccurrences(of: "\\n", with: "\n")
                                continuation.yield(.token(decoded))
                            case "done":
                                continuation.yield(.done)
                                continuation.finish()
                                return
                            default:
                                break
                            }
                        }
                        // Ignore empty lines, comments (: ping), etc.
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - Memory

    func fetchMemory() async throws -> MemoryResponse {
        let url = URL(string: "\(baseURL)/memory")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode(MemoryResponse.self, from: data)
    }

    func deleteMemory(id: Int) async throws {
        let url = URL(string: "\(baseURL)/memory/\(id)")!
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        let _ = try await URLSession.shared.data(for: request)
    }

    // MARK: - Highlight Explain

    func explainHighlight(id: Int) async throws -> HighlightExplanation {
        let url = URL(string: "\(baseURL)/highlights/\(id)/explain")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode(HighlightExplanation.self, from: data)
    }

    // MARK: - Stats

    func fetchStats() async throws -> LibraryStats {
        let url = URL(string: "\(baseURL)/stats")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode(LibraryStats.self, from: data)
    }
}

enum SSEEvent {
    case sources([ChatSource])
    case thinking(String)
    case token(String)
    case done
}
