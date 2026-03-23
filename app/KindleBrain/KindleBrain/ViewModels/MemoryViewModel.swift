import SwiftUI

@MainActor
class MemoryViewModel: ObservableObject {
    @Published var memories: [UserMemory] = []
    @Published var conversations: [ConversationSummary] = []
    @Published var interests: [ReadingInterest] = []
    @Published var isLoading = false
    @Published var error: String?

    private let api = APIService.shared

    func load() async {
        isLoading = true
        error = nil
        do {
            let response = try await api.fetchMemory()
            memories = response.memories
            conversations = response.recentConversations
            interests = response.topInterests
        } catch {
            self.error = "Could not load memory: \(error.localizedDescription)"
        }
        isLoading = false
    }

    func deleteMemory(_ memory: UserMemory) async {
        do {
            try await api.deleteMemory(id: memory.id)
            memories.removeAll { $0.id == memory.id }
        } catch {
            self.error = "Could not delete memory: \(error.localizedDescription)"
        }
    }
}
