import SwiftUI

struct ContentView: View {
    @EnvironmentObject var chatVM: ChatViewModel
    @EnvironmentObject var libraryVM: LibraryViewModel
    @EnvironmentObject var memoryVM: MemoryViewModel
    @EnvironmentObject var serverManager: ServerManager
    @State private var selectedTab: Tab = .chat

    enum Tab: String, CaseIterable {
        case chat = "Chat"
        case library = "Library"
        case memory = "Memory"
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            if !serverManager.isRunning {
                serverStartingView
            } else {
                switch selectedTab {
                case .chat:
                    ChatView()
                case .library:
                    LibraryDetailView()
                case .memory:
                    MemoryView()
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("Tab", selection: $selectedTab) {
                    ForEach(Tab.allCases, id: \.self) { tab in
                        Label(tab.rawValue, systemImage: iconForTab(tab))
                            .tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 260)
            }
        }
        .focusedSceneValue(\.selectedTab, $selectedTab)
        .task {
            while !serverManager.isRunning {
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
            await libraryVM.loadBooks()
            await libraryVM.loadStats()
        }
    }

    private var serverStartingView: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.5)
            Text(serverManager.statusMessage)
                .font(.title3)
                .foregroundStyle(.secondary)
            Text("The Python API server is starting up...")
                .font(.callout)
                .foregroundStyle(.tertiary)
        }
    }

    private var sidebar: some View {
        VStack(spacing: 0) {
            switch selectedTab {
            case .chat:
                chatSidebar
            case .library:
                librarySidebar
            case .memory:
                memorySidebar
            }
        }
        .navigationSplitViewColumnWidth(min: 260, ideal: 310, max: 420)
    }

    private func iconForTab(_ tab: Tab) -> String {
        switch tab {
        case .chat: return "bubble.left.and.bubble.right"
        case .library: return "books.vertical"
        case .memory: return "brain"
        }
    }

    // MARK: - Chat Sidebar

    private var chatSidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Server status
            HStack(spacing: 8) {
                Circle()
                    .fill(serverManager.isRunning ? Color(nsColor: .systemGreen) : Color(nsColor: .systemOrange))
                    .frame(width: 8, height: 8)
                Text(serverManager.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 8)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Server status: \(serverManager.statusMessage)")

            // New Chat button
            Button {
                chatVM.newConversation()
            } label: {
                Label("New Chat", systemImage: "plus.bubble")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
            .keyboardShortcut("n", modifiers: .command)

            Divider()

            // Conversation history
            if chatVM.conversations.isEmpty {
                VStack(spacing: 16) {
                    Spacer()

                    GroupBox {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(chatVM.suggestions, id: \.self) { suggestion in
                                Button {
                                    chatVM.inputText = suggestion
                                    Task { await chatVM.send() }
                                } label: {
                                    HStack(spacing: 6) {
                                        Image(systemName: "sparkle")
                                            .font(.caption2)
                                            .foregroundStyle(.orange)
                                        Text(suggestion)
                                            .font(.callout)
                                            .multilineTextAlignment(.leading)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .padding(.vertical, 5)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Ask: \(suggestion)")
                            }
                        }
                    } label: {
                        Label("Quick Questions", systemImage: "questionmark.bubble")
                            .font(.headline)
                    }
                    .padding(.horizontal, 16)

                    Spacer()
                }
            } else {
                List {
                    ForEach(chatVM.conversations) { conv in
                        Button {
                            Task { await chatVM.selectConversation(conv) }
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(conv.title)
                                    .font(.callout)
                                    .lineLimit(2)
                                    .foregroundStyle(chatVM.currentConversationId == conv.id ? Color.accentColor : .primary)
                                Text(conv.updatedAt, style: .relative)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .background(
                            chatVM.currentConversationId == conv.id
                                ? Color.accentColor.opacity(0.08)
                                : Color.clear
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .contextMenu {
                            Button(role: .destructive) {
                                Task { await chatVM.deleteConversation(conv) }
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                    .onDelete { indexSet in
                        for index in indexSet {
                            let conv = chatVM.conversations[index]
                            Task { await chatVM.deleteConversation(conv) }
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        }
        .task {
            await chatVM.loadConversations()
        }
    }

    // MARK: - Memory Sidebar

    private var memorySidebar: some View {
        VStack(alignment: .leading, spacing: 12) {
            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    Label("\(memoryVM.memories.count) facts learned", systemImage: "lightbulb.fill")
                        .font(.callout)
                    Label("\(memoryVM.conversations.count) conversations", systemImage: "text.bubble")
                        .font(.callout)
                    Label("\(memoryVM.interests.count) topics tracked", systemImage: "sparkles")
                        .font(.callout)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Label("Memory Overview", systemImage: "brain")
                    .font(.headline)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)

            Divider()

            if !memoryVM.memories.isEmpty {
                List {
                    let categories = Set(memoryVM.memories.map(\.category)).sorted()
                    ForEach(categories, id: \.self) { category in
                        let count = memoryVM.memories.filter { $0.category == category }.count
                        Label("\(category.capitalized) (\(count))", systemImage: categoryIcon(category))
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .listStyle(.sidebar)
            } else {
                VStack(spacing: 12) {
                    Spacer()
                    Text("Memory is empty")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Text("Start chatting and Kindle Brain will learn about you.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                    Spacer()
                }
                .padding(.horizontal, 16)
            }
        }
        .task {
            await memoryVM.load()
        }
    }

    private func categoryIcon(_ category: String) -> String {
        switch category.lowercased() {
        case "profesion": return "briefcase.fill"
        case "intereses": return "star.fill"
        case "preferencias": return "slider.horizontal.3"
        case "contexto_personal": return "person.fill"
        case "metas": return "target"
        default: return "lightbulb.fill"
        }
    }

    // MARK: - Library Sidebar

    private var librarySidebar: some View {
        List(libraryVM.filteredBooks, selection: $libraryVM.selectedBook) { book in
            BookRow(book: book)
                .tag(book)
                .contextMenu {
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(book.title, forType: .string)
                    } label: {
                        Label("Copy Title", systemImage: "doc.on.doc")
                    }
                }
        }
        .searchable(text: $libraryVM.searchQuery, prompt: "Search books...")
        .onChange(of: libraryVM.selectedBook) { _, newBook in
            if let book = newBook {
                libraryVM.selectBook(book)
            }
        }
    }
}

struct BookRow: View {
    let book: Book

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(book.title)
                .font(.headline)
                .lineLimit(2)

            if let author = book.author {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Label("\(book.highlightCount) highlights", systemImage: "text.quote")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 4)
    }
}
