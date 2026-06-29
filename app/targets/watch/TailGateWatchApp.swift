import SwiftUI

@main
struct TailGateWatchApp: App {
    @StateObject private var store = DoorStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
