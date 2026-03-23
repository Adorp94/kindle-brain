import SwiftUI

struct ContentView: View {
    @EnvironmentObject var chatVM: ChatViewModel
    @EnvironmentObject var libraryVM: LibraryViewModel
    @State private var selectedTab: Tab = .chat

    enum Tab: String, CaseIterable {
        case chat = "Chat"
        case library = "Library"
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            switch selectedTab {
            case .chat:
                ChatView()
            case .library:
                LibraryDetailView()
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
            await libraryVM.loadBooks()
            await libraryVM.loadStats()
        }
    }

    private var sidebar: some View {
        VStack(spacing: 0) {
            switch selectedTab {
            case .chat:
                chatSidebar
            case .library:
                librarySidebar
            }
        }
        .navigationSplitViewColumnWidth(min: 260, ideal: 310, max: 420)
    }

    private func iconForTab(_ tab: Tab) -> String {
        switch tab {
        case .chat: return "bubble.left.and.bubble.right"
        case .library: return "books.vertical"
        }
    }

    // MARK: - Chat Sidebar

    private var chatSidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
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
