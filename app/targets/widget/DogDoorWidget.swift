import WidgetKit
import SwiftUI
import AppIntents

// MARK: - Data Models

struct DoorData: Codable {
    var state: String
    var open_pct: Double?
}

struct OwnerInfo: Codable {
    var available: Bool
}

struct OwnersData: Codable {
    var owner1: OwnerInfo?
    var owner2: OwnerInfo?
}

// MARK: - Timeline Entry

struct DogDoorEntry: TimelineEntry {
    let date: Date
    let doorState: String
    let openPercent: Double
    let owner1Available: Bool
    let owner2Available: Bool
}

// MARK: - Firebase fetching

private let firebaseBase = "https://dog-door-632e6-default-rtdb.firebaseio.com"

private func fetchDoor() async -> DoorData? {
    guard let url = URL(string: "\(firebaseBase)/door.json") else { return nil }
    var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
    guard let (data, _) = try? await URLSession.shared.data(for: request) else { return nil }
    return try? JSONDecoder().decode(DoorData.self, from: data)
}

private func fetchOwners() async -> OwnersData? {
    guard let url = URL(string: "\(firebaseBase)/owners.json") else { return nil }
    var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
    guard let (data, _) = try? await URLSession.shared.data(for: request) else { return nil }
    return try? JSONDecoder().decode(OwnersData.self, from: data)
}

// MARK: - Timeline Provider

struct DogDoorProvider: TimelineProvider {
    func placeholder(in context: Context) -> DogDoorEntry {
        DogDoorEntry(date: .now, doorState: "closed", openPercent: 0,
                     owner1Available: true, owner2Available: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (DogDoorEntry) -> Void) {
        completion(placeholder(in: context))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<DogDoorEntry>) -> Void) {
        Task {
            async let door = fetchDoor()
            async let owners = fetchOwners()
            let (d, o) = await (door, owners)

            let entry = DogDoorEntry(
                date: .now,
                doorState: d?.state ?? "unknown",
                openPercent: d?.open_pct ?? 0,
                owner1Available: o?.owner1?.available ?? true,
                owner2Available: o?.owner2?.available ?? true
            )
            let next = Date.now.addingTimeInterval(30)
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }
}

// MARK: - Anonymous auth token

private let firebaseApiKey = "AIzaSyAJewDTn21UBdteXwjF97S3sabz4Ya9zOo"
private let tokenStoreKey  = "widget_firebase_token"
private let tokenExpiryKey = "widget_firebase_token_expiry"

private func cachedToken() -> String? {
    let d = UserDefaults.standard
    guard let token  = d.string(forKey: tokenStoreKey),
          let expiry = d.object(forKey: tokenExpiryKey) as? Date,
          expiry > Date.now.addingTimeInterval(60)
    else { return nil }
    return token
}

private func freshAnonToken() async -> String? {
    guard let url = URL(string: "https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=\(firebaseApiKey)") else { return nil }
    var req = URLRequest(url: url)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = #"{"returnSecureToken":true}"#.data(using: .utf8)
    guard let (data, _) = try? await URLSession.shared.data(for: req),
          let json      = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let token     = json["idToken"] as? String,
          let ttlStr    = json["expiresIn"] as? String,
          let ttl       = Double(ttlStr)
    else { return nil }
    let d = UserDefaults.standard
    d.set(token, forKey: tokenStoreKey)
    d.set(Date.now.addingTimeInterval(ttl), forKey: tokenExpiryKey)
    return token
}

private func anonToken() async -> String? {
    cachedToken() ?? (await freshAnonToken())
}

// MARK: - AppIntents

private func sendCommand(_ command: String) async {
    guard let token = await anonToken(),
          let url   = URL(string: "\(firebaseBase)/command.json?auth=\(token)")
    else { return }
    var request = URLRequest(url: url)
    request.httpMethod = "PUT"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = "\"\(command)\"".data(using: .utf8)
    _ = try? await URLSession.shared.data(for: request)
}

struct OpenDoorIntent: AppIntent {
    static var title: LocalizedStringResource = "Open Door"
    func perform() async throws -> some IntentResult {
        await sendCommand("open")
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        return .result()
    }
}

struct CloseDoorIntent: AppIntent {
    static var title: LocalizedStringResource = "Close Door"
    func perform() async throws -> some IntentResult {
        await sendCommand("close")
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        return .result()
    }
}

// MARK: - Views

struct OwnerRow: View {
    let label: String
    let available: Bool

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: available ? "person.fill.checkmark" : "person.fill.xmark")
                .font(.caption2)
                .foregroundStyle(available ? Color.blue : Color.secondary)
            Text(label)
                .font(.caption2)
                .foregroundStyle(available ? Color.primary : Color.secondary)
        }
    }
}

struct DogDoorWidgetView: View {
    let entry: DogDoorEntry

    private var dotColor: Color {
        switch entry.doorState {
        case "open":             return .green
        case "partially_open":   return .yellow
        case "partially_closed": return .orange
        case "closed":           return .red
        default:                 return .gray
        }
    }

    private var statusLabel: String {
        switch entry.doorState {
        case "partially_open":   return "Opening..."
        case "partially_closed": return "Closing..."
        default:
            return entry.doorState
                .replacingOccurrences(of: "_", with: " ")
                .capitalized
        }
    }

    private var canOpen: Bool { entry.owner1Available && entry.owner2Available }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Puppy Play Time")
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundStyle(.secondary)

            HStack(spacing: 6) {
                Circle()
                    .fill(dotColor)
                    .frame(width: 10, height: 10)
                VStack(alignment: .leading, spacing: 1) {
                    Text(statusLabel)
                        .font(.headline)
                        .fontWeight(.bold)
                    Text("\(Int(entry.openPercent))% open")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            HStack(spacing: 12) {
                OwnerRow(label: "Owner 1", available: entry.owner1Available)
                OwnerRow(label: "Owner 2", available: entry.owner2Available)
                Spacer()
            }

            Spacer(minLength: 0)

            HStack(spacing: 8) {
                Button(intent: OpenDoorIntent()) {
                    Label("Open", systemImage: "door.left.hand.open")
                        .font(.caption)
                        .fontWeight(.medium)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(canOpen ? .green : Color(UIColor.systemGray4))

                Button(intent: CloseDoorIntent()) {
                    Label("Close", systemImage: "door.left.hand.closed")
                        .font(.caption)
                        .fontWeight(.medium)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
            }
        }
        .padding(14)
    }
}

// MARK: - Widget

@main
struct DogDoorWidget: Widget {
    let kind = "DogDoorWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: DogDoorProvider()) { entry in
            DogDoorWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Puppy Play Time")
        .description("Control your dog door from your home screen.")
        .supportedFamilies([.systemMedium])
    }
}
