import SwiftUI

@MainActor
class MemoryViewModel: ObservableObject {
    @Published var memories: [UserMemory] = []
    @Published var conversations: [ConversationSummary] = []
    @Published var interests: [ReadingInterest] = []
    @Published var isLoading = false
    @Published var error: String?

    private let data = DataService.shared

    func load() async {
        isLoading = true
        error = nil
        let response = await data.fetchMemory()
        memories = response.memories
        conversations = response.recentConversations
        interests = response.topInterests
        isLoading = false
    }

    func deleteMemory(_ memory: UserMemory) async {
        await data.deleteMemory(id: memory.id)
        memories.removeAll { $0.id == memory.id }
    }
}
