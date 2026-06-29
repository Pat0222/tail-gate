import SwiftUI

// MARK: - Models

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

// MARK: - Anonymous auth (same pattern as widget)

private let firebaseBase   = "https://dog-door-632e6-default-rtdb.firebaseio.com"
private let firebaseApiKey = "AIzaSyAJewDTn21UBdteXwjF97S3sabz4Ya9zOo"
private let tokenKey       = "watch_anon_token"
private let tokenExpiryKey = "watch_anon_expiry"

private func cachedToken() -> String? {
    let d = UserDefaults.standard
    guard let token  = d.string(forKey: tokenKey),
          let expiry = d.object(forKey: tokenExpiryKey) as? Date,
          expiry > Date().addingTimeInterval(60)
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
          let json    = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let token   = json["idToken"] as? String,
          let ttlStr  = json["expiresIn"] as? String,
          let ttl     = Double(ttlStr)
    else { return nil }
    let d = UserDefaults.standard
    d.set(token, forKey: tokenKey)
    d.set(Date().addingTimeInterval(ttl), forKey: tokenExpiryKey)
    return token
}

private func anonToken() async -> String? {
    if let t = cachedToken() { return t }
    return await freshAnonToken()
}

// MARK: - Store

@MainActor
class DoorStore: ObservableObject {
    @Published var doorState: String = "unknown"
    @Published var openPct: Double   = 0
    @Published var owner1: Bool      = false
    @Published var owner2: Bool      = false
    @Published var connected: Bool   = false

    private var pollTask: Task<Void, Never>?

    func startPolling() {
        guard pollTask == nil else { return }
        pollTask = Task {
            while !Task.isCancelled {
                await fetchAll()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func sendCommand(_ command: String) async {
        guard let token = await anonToken(),
              let url   = URL(string: "\(firebaseBase)/command.json?auth=\(token)")
        else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "PUT"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = "\"\(command)\"".data(using: .utf8)
        _ = try? await URLSession.shared.data(for: req)
        try? await Task.sleep(for: .seconds(1.5))
        await fetchAll()
    }

    func setOwner(_ path: String, available: Bool) async {
        guard let token = await anonToken(),
              let url   = URL(string: "\(firebaseBase)/\(path)/available.json?auth=\(token)")
        else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "PUT"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = (available ? "true" : "false").data(using: .utf8)
        _ = try? await URLSession.shared.data(for: req)
        await fetchAll()
    }

    private func fetchAll() async {
        guard let token = await anonToken() else { connected = false; return }
        async let d = fetchDoor(token: token)
        async let o = fetchOwners(token: token)
        let (door, owners) = await (d, o)
        if let door {
            doorState = door.state
            openPct   = door.open_pct ?? 0
            connected = true
        } else {
            connected = false
        }
        if let owners {
            owner1 = owners.owner1?.available ?? false
            owner2 = owners.owner2?.available ?? false
        }
    }

    private func fetchDoor(token: String) async -> DoorData? {
        guard let url = URL(string: "\(firebaseBase)/door.json?auth=\(token)") else { return nil }
        guard let (data, _) = try? await URLSession.shared.data(from: url) else { return nil }
        return try? JSONDecoder().decode(DoorData.self, from: data)
    }

    private func fetchOwners(token: String) async -> OwnersData? {
        guard let url = URL(string: "\(firebaseBase)/owners.json?auth=\(token)") else { return nil }
        guard let (data, _) = try? await URLSession.shared.data(from: url) else { return nil }
        return try? JSONDecoder().decode(OwnersData.self, from: data)
    }
}
