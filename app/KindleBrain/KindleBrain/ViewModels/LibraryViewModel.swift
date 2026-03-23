import SwiftUI

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var books: [Book] = []
    @Published var selectedBook: Book?
    @Published var highlights: [Highlight] = []
    @Published var bookInfo: BookInfo?
    @Published var searchQuery = ""
    @Published var highlightSearch = ""
    @Published var searchResults: [SearchResult] = []
    @Published var isLoading = false
    @Published var stats: LibraryStats?

    private let api = APIService.shared
    private var loadTask: Task<Void, Never>?

    var filteredBooks: [Book] {
        if searchQuery.isEmpty {
            return books
        }
        let q = searchQuery.lowercased()
        return books.filter {
            $0.title.lowercased().contains(q) ||
            ($0.author?.lowercased().contains(q) ?? false)
        }
    }

    var filteredHighlights: [Highlight] {
        if highlightSearch.isEmpty {
            return highlights
        }
        let q = highlightSearch.lowercased()
        return highlights.filter {
            $0.text.lowercased().contains(q) ||
            ($0.chapter?.lowercased().contains(q) ?? false) ||
            ($0.note?.lowercased().contains(q) ?? false)
        }
    }

    func loadBooks() async {
        isLoading = true
        do {
            books = try await api.fetchBooks()
        } catch {
            print("Error loading books: \(error)")
        }
        isLoading = false
    }

    func selectBook(_ book: Book) {
        // Cancel any in-flight load
        loadTask?.cancel()
        selectedBook = book
        highlights = []
        bookInfo = nil
        highlightSearch = ""
        isLoading = true

        loadTask = Task {
            do {
                let response = try await api.fetchBookHighlights(bookId: book.id)
                guard !Task.isCancelled else { return }
                // Verify we're still on the same book
                guard selectedBook?.id == book.id else { return }
                highlights = response.highlights
                bookInfo = response.book
            } catch {
                if !Task.isCancelled {
                    print("Error loading highlights: \(error)")
                }
            }
            if !Task.isCancelled {
                isLoading = false
            }
        }
    }

    func search() async {
        guard !searchQuery.trimmingCharacters(in: .whitespaces).isEmpty else {
            searchResults = []
            return
        }
        isLoading = true
        do {
            searchResults = try await api.search(query: searchQuery)
        } catch {
            print("Error searching: \(error)")
        }
        isLoading = false
    }

    func loadStats() async {
        do {
            stats = try await api.fetchStats()
        } catch {
            print("Error loading stats: \(error)")
        }
    }
}
