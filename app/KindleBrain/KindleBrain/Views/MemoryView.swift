import SwiftUI

struct MemoryView: View {
    @EnvironmentObject var memoryVM: MemoryViewModel
    @State private var selectedSection: MemorySection = .profile

    enum MemorySection: String, CaseIterable {
        case profile = "Profile"
        case conversations = "Conversations"
        case interests = "Interests"
    }

    var body: some View {
        VStack(spacing: 0) {
            // Section picker
            Picker("", selection: $selectedSection) {
                ForEach(MemorySection.allCases, id: \.self) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .padding()

            if memoryVM.isLoading {
                Spacer()
                ProgressView("Loading memory...")
                Spacer()
            } else if let error = memoryVM.error {
                Spacer()
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.largeTitle)
                        .foregroundStyle(.orange)
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Retry") {
                        Task { await memoryVM.load() }
                    }
                    .buttonStyle(.bordered)
                }
                .padding()
                Spacer()
            } else {
                switch selectedSection {
                case .profile:
                    profileSection
                case .conversations:
                    conversationsSection
                case .interests:
                    interestsSection
                }
            }
        }
        .navigationTitle("Memory")
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button {
                    Task { await memoryVM.load() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Refresh memory")
            }
        }
        .task {
            if memoryVM.memories.isEmpty && memoryVM.conversations.isEmpty {
                await memoryVM.load()
            }
        }
    }

    // MARK: - Profile (User Memories)

    private var profileSection: some View {
        Group {
            if memoryVM.memories.isEmpty {
                emptySection(
                    icon: "brain",
                    title: "No memories yet",
                    subtitle: "Chat with Kindle Brain and it will learn about you over time."
                )
            } else {
                List {
                    ForEach(groupedMemories, id: \.category) { group in
                        Section(group.category.capitalized) {
                            ForEach(group.memories) { memory in
                                MemoryFactRow(memory: memory) {
                                    Task { await memoryVM.deleteMemory(memory) }
                                }
                            }
                        }
                    }
                }
                .listStyle(.inset)
            }
        }
    }

    private var groupedMemories: [(category: String, memories: [UserMemory])] {
        let dict = Dictionary(grouping: memoryVM.memories, by: { $0.category })
        return dict.map { (category: $0.key, memories: $0.value) }
            .sorted { $0.category < $1.category }
    }

    // MARK: - Conversations

    private var conversationsSection: some View {
        Group {
            if memoryVM.conversations.isEmpty {
                emptySection(
                    icon: "bubble.left.and.text.bubble.right",
                    title: "No conversation history",
                    subtitle: "Past conversations will appear here as summaries."
                )
            } else {
                List(memoryVM.conversations) { summary in
                    ConversationSummaryRow(summary: summary)
                }
                .listStyle(.inset)
            }
        }
    }

    // MARK: - Interests

    private var interestsSection: some View {
        Group {
            if memoryVM.interests.isEmpty {
                emptySection(
                    icon: "sparkles",
                    title: "No interests tracked",
                    subtitle: "Topics you ask about frequently will appear here."
                )
            } else {
                List(memoryVM.interests) { interest in
                    InterestRow(interest: interest)
                }
                .listStyle(.inset)
            }
        }
    }

    // MARK: - Empty State

    private func emptySection(icon: String, title: String, subtitle: String) -> some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: icon)
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.title3.bold())
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Spacer()
        }
        .padding()
    }
}

// MARK: - Row Views

struct MemoryFactRow: View {
    let memory: UserMemory
    let onDelete: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: iconForCategory(memory.category))
                .font(.body)
                .foregroundStyle(.orange)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 4) {
                Text(memory.fact)
                    .font(.body)

                HStack(spacing: 8) {
                    Text(formatDate(memory.createdAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)

                    if memory.confidence < 1.0 {
                        Text("\(Int(memory.confidence * 100))% confidence")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }

            Spacer()

            Button(role: .destructive) {
                onDelete()
            } label: {
                Image(systemName: "trash")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("Delete this memory")
        }
        .padding(.vertical, 4)
    }

    private func iconForCategory(_ category: String) -> String {
        switch category.lowercased() {
        case "profesion": return "briefcase.fill"
        case "intereses": return "star.fill"
        case "preferencias": return "slider.horizontal.3"
        case "contexto_personal": return "person.fill"
        case "metas": return "target"
        default: return "lightbulb.fill"
        }
    }

    private func formatDate(_ isoDate: String) -> String {
        let prefix = String(isoDate.prefix(10))
        return prefix
    }
}

struct ConversationSummaryRow: View {
    let summary: ConversationSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(summary.userQuery)
                .font(.callout.bold())
                .lineLimit(2)

            Text(summary.summary)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(3)

            HStack(spacing: 8) {
                if let topics = summary.topics, !topics.isEmpty, topics != "[]" {
                    let parsed = parseTopics(topics)
                    if !parsed.isEmpty {
                        ForEach(parsed.prefix(3), id: \.self) { topic in
                            Text(topic)
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.orange.opacity(0.1))
                                .clipShape(Capsule())
                        }
                    }
                }

                Spacer()

                Text(String(summary.createdAt.prefix(10)))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 4)
    }

    private func parseTopics(_ raw: String) -> [String] {
        // Topics come as JSON array string e.g. '["topic1","topic2"]'
        guard let data = raw.data(using: .utf8),
              let arr = try? JSONDecoder().decode([String].self, from: data) else {
            return []
        }
        return arr
    }
}

struct InterestRow: View {
    let interest: ReadingInterest

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(interest.topic)
                    .font(.body.bold())

                if let lastQuery = interest.lastQuery {
                    Text(lastQuery)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text("\(interest.queryCount)")
                    .font(.title3.bold())
                    .foregroundStyle(.orange)
                Text(interest.queryCount == 1 ? "query" : "queries")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 4)
    }
}
