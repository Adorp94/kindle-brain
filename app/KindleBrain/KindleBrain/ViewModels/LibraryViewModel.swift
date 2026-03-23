import SwiftUI

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var books: [Book] = []
    @Published var selectedBook: Book?
    @Published var highlights: [Highlight] = []
    @Published var bookInfo: BookInfo?
    @Published var searchQuery = ""
    @Published var highlightSearch = ""
    @Published var isLoading = false
    @Published var stats: LibraryStats?

    private var data: DataService { DataService.shared }
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
        books = await data.fetchBooks()
        isLoading = false
    }

    func selectBook(_ book: Book) {
        loadTask?.cancel()
        selectedBook = book
        highlights = []
        bookInfo = nil
        highlightSearch = ""
        isLoading = true

        loadTask = Task {
            let response = await data.fetchBookHighlights(bookId: book.id)
            guard !Task.isCancelled, selectedBook?.id == book.id else { return }
            highlights = response?.highlights ?? []
            bookInfo = response?.book
            if !Task.isCancelled { isLoading = false }
        }
    }

    func loadStats() async {
        stats = await data.fetchStats()
    }
}
