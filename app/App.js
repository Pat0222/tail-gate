import { useEffect, useState } from 'react';
import { StyleSheet, Text, View, Switch, TouchableOpacity, SafeAreaView, ActivityIndicator, Platform, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue, set } from 'firebase/database';
import { db } from './firebase';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';

const DOOR_COLORS = {
  open:             '#34C759',
  closed:           '#FF3B30',
  partially_open:   '#FF9500',
  partially_closed: '#FF9500',
};

const LED_COLORS = {
  green:  '#34C759',
  yellow: '#FF9500',
  red:    '#FF3B30',
  blue:   '#007AFF',
  white:  '#8E8E93',
};

const INIT_LEDS = { green: false, yellow: false, red: false, blue: false, white: false };

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

async function registerForPushNotifications() {
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.MAX,
    });
  }
  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== 'granted') return null;

  const projectId = Constants.easConfig?.projectId
    ?? Constants.expoConfig?.extra?.eas?.projectId;
  if (!projectId) return null;

  const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  return token;
}

export default function App() {
  const [screen, setScreen]     = useState('home');
  const [doorState, setDoorState] = useState('unknown');
  const [openPct, setOpenPct]   = useState(0);
  const [owner1, setOwner1]     = useState(false);
  const [owner2, setOwner2]     = useState(false);
  const [testLeds, setTestLeds]             = useState({ ...INIT_LEDS });
  const [testSwitchState, setTestSwitchState] = useState({ open: false, close: false });
  const [nightMode, setNightModeState]      = useState('auto');

  useEffect(() => {
    const unsubDoor = onValue(ref(db, 'door'), snapshot => {
      const data = snapshot.val();
      if (data) {
        setDoorState(data.state ?? 'unknown');
        setOpenPct(data.open_pct ?? 0);
      }
    });

    const unsubOwners = onValue(ref(db, 'owners'), snapshot => {
      const data = snapshot.val();
      if (data) {
        setOwner1(data.owner1?.available ?? false);
        setOwner2(data.owner2?.available ?? false);
      }
    });

    const unsubNightMode = onValue(ref(db, 'settings/night_mode_override'), snapshot => {
      const val = snapshot.val();
      if (val === null || val === undefined) setNightModeState('auto');
      else setNightModeState(val ? 'on' : 'off');
    });

    registerForPushNotifications().then(token => {
      if (token) {
        const key = token.replace(/[[\]]/g, '');
        set(ref(db, `push_tokens/${key}`), token);
      }
    });

    return () => { unsubDoor(); unsubOwners(); unsubNightMode(); };
  }, []);

  useEffect(() => {
    if (screen !== 'testing') return;
    const unsub = onValue(ref(db, 'test/switch_state'), snapshot => {
      const data = snapshot.val();
      setTestSwitchState(data ?? { open: false, close: false });
    });
    return () => unsub();
  }, [screen]);

  const setOwnerAvailable = (owner, value) => {
    set(ref(db, `owners/${owner}`), { available: value });
  };

  const sendCommand = (cmd) => {
    set(ref(db, 'command'), cmd);
  };

  const enterTesting = () => {
    const leds = { ...INIT_LEDS };
    setTestLeds(leds);
    set(ref(db, 'test'), { active: true, leds });
    setScreen('testing');
  };

  const exitTesting = () => {
    set(ref(db, 'test'), null);
    setScreen('settings');
  };

  const toggleLed = (color, value) => {
    const updated = { ...testLeds, [color]: value };
    setTestLeds(updated);
    set(ref(db, 'test/leds'), updated);
  };

  const toggleAll = (value) => {
    const updated = Object.fromEntries(Object.keys(INIT_LEDS).map(k => [k, value]));
    setTestLeds(updated);
    set(ref(db, 'test/leds'), updated);
  };

  const simulateSwitch = (direction) => {
    set(ref(db, 'test/switch'), direction);
  };

  const setNightMode = (value) => {
    setNightModeState(value);
    set(ref(db, 'settings/night_mode_override'), value === 'auto' ? null : value === 'on');
  };

  const isMoving      = doorState === 'partially_open' || doorState === 'partially_closed';
  const statusColor   = DOOR_COLORS[doorState] ?? '#8E8E93';
  const statusLabel   = isMoving
    ? (doorState === 'partially_open' ? 'Opening...' : 'Closing...')
    : doorState.replace(/_/g, ' ');
  const bothAvailable = owner1 && owner2;
  const allOn         = Object.values(testLeds).every(Boolean);

  // Settings screen
  if (screen === 'settings') {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.navHeader}>
          <TouchableOpacity onPress={() => setScreen('home')} style={styles.backButton}>
            <Ionicons name="chevron-back" size={24} color="#007AFF" />
            <Text style={styles.backText}>Back</Text>
          </TouchableOpacity>
          <Text style={styles.navTitle}>Settings</Text>
          <View style={styles.navSpacer} />
        </View>
        <View style={styles.navSeparator} />

        <Text style={styles.sectionHeader}>LED Brightness</Text>
        <View style={styles.card}>
          <View style={styles.settingsRowLeft}>
            <View style={[styles.settingsIconBg, { backgroundColor: '#FF9500' }]}>
              <Ionicons name="moon-outline" size={16} color="#fff" />
            </View>
            <Text style={styles.settingsRowText}>Night Mode</Text>
          </View>
          <View style={styles.segmentedControl}>
            {[['auto', 'Auto'], ['on', 'Night'], ['off', 'Day']].map(([value, label]) => (
              <TouchableOpacity
                key={value}
                style={[styles.segment, nightMode === value && styles.segmentActive]}
                onPress={() => setNightMode(value)}
              >
                <Text style={[styles.segmentText, nightMode === value && styles.segmentTextActive]}>
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.sectionDesc}>
            {nightMode === 'auto' ? 'Dims automatically 10 PM – 7 AM'
              : nightMode === 'on' ? 'LEDs dimmed'
              : 'LEDs at full brightness'}
          </Text>
        </View>

        <Text style={styles.sectionHeader}>Diagnostic Tools</Text>
        <View style={styles.card}>
          <TouchableOpacity style={styles.settingsRow} onPress={enterTesting}>
            <View style={styles.settingsRowLeft}>
              <View style={[styles.settingsIconBg, { backgroundColor: '#5856D6' }]}>
                <Ionicons name="construct-outline" size={16} color="#fff" />
              </View>
              <Text style={styles.settingsRowText}>Testing</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color="#C7C7CC" />
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // Testing screen
  if (screen === 'testing') {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.navHeader}>
          <TouchableOpacity onPress={exitTesting} style={styles.backButton}>
            <Ionicons name="chevron-back" size={24} color="#007AFF" />
            <Text style={styles.backText}>Settings</Text>
          </TouchableOpacity>
          <Text style={styles.navTitle}>Testing</Text>
          <View style={styles.navSpacer} />
        </View>
        <View style={styles.navSeparator} />

        <ScrollView showsVerticalScrollIndicator={false}>

          <Text style={styles.sectionHeader}>LED Control</Text>
          <View style={styles.card}>
            <View style={styles.allLedsRow}>
              <Text style={styles.allLedsLabel}>All LEDs</Text>
              <Switch
                value={allOn}
                onValueChange={toggleAll}
                trackColor={{ false: '#E5E5EA', true: '#8E8E93' }}
              />
            </View>
            {Object.keys(INIT_LEDS).map(color => (
              <View key={color} style={[styles.ownerRow, styles.ownerRowDivider]}>
                <View style={styles.ledLabelRow}>
                  <View style={[styles.ledDot, {
                    backgroundColor: testLeds[color] ? LED_COLORS[color] : '#E5E5EA',
                  }]} />
                  <Text style={styles.ownerLabel}>{color.charAt(0).toUpperCase() + color.slice(1)}</Text>
                </View>
                <Switch
                  value={testLeds[color]}
                  onValueChange={v => toggleLed(color, v)}
                  trackColor={{ false: '#E5E5EA', true: LED_COLORS[color] }}
                />
              </View>
            ))}
          </View>

          <Text style={styles.sectionHeader}>Switch Signal</Text>
          <Text style={styles.sectionDesc}>Flip the manual switch to test without moving the actuator.</Text>
          <View style={styles.card}>
            <View style={styles.ownerRow}>
              <Text style={styles.ownerLabel}>Open</Text>
              <View style={styles.signalStatus}>
                <View style={[styles.signalDot, { backgroundColor: testSwitchState.open ? '#34C759' : '#C7C7CC' }]} />
                <Text style={[styles.signalLabel, { color: testSwitchState.open ? '#34C759' : '#C7C7CC' }]}>
                  {testSwitchState.open ? 'Active' : 'None'}
                </Text>
              </View>
            </View>
            <View style={[styles.ownerRow, styles.ownerRowDivider]}>
              <Text style={styles.ownerLabel}>Close</Text>
              <View style={styles.signalStatus}>
                <View style={[styles.signalDot, { backgroundColor: testSwitchState.close ? '#FF3B30' : '#C7C7CC' }]} />
                <Text style={[styles.signalLabel, { color: testSwitchState.close ? '#FF3B30' : '#C7C7CC' }]}>
                  {testSwitchState.close ? 'Active' : 'None'}
                </Text>
              </View>
            </View>
          </View>

          <Text style={styles.sectionHeader}>Simulate Switch</Text>
          <Text style={styles.sectionDesc}>Moves the actuator — make sure the L298N is connected.</Text>
          <View style={[styles.card, { marginBottom: 32 }]}>
            <TouchableOpacity
              style={[styles.button, styles.openButton]}
              onPress={() => simulateSwitch('open')}
            >
              <Text style={styles.buttonText}>Simulate Open</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.button, styles.closeButton]}
              onPress={() => simulateSwitch('close')}
            >
              <Text style={styles.buttonText}>Simulate Close</Text>
            </TouchableOpacity>
          </View>

        </ScrollView>
      </SafeAreaView>
    );
  }

  // Home screen
  return (
    <SafeAreaView style={styles.container}>

      <View style={styles.titleRow}>
        <Text style={styles.title}>Puppy Play Time</Text>
        <TouchableOpacity onPress={() => setScreen('settings')}>
          <Ionicons name="settings-outline" size={28} color="#8E8E93" />
        </TouchableOpacity>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Door Status</Text>
        <View style={styles.statusRow}>
          {isMoving
            ? <ActivityIndicator size="small" color={statusColor} />
            : <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
          }
          <Text style={[styles.statusText, isMoving && { color: statusColor }]}>{statusLabel}</Text>
          <Text style={styles.pctText}>{Math.max(0, Math.min(100, openPct))}% open</Text>
        </View>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Owner Availability</Text>
        <View style={styles.ownerRow}>
          <Text style={styles.ownerLabel}>Rita</Text>
          <Switch
            value={owner1}
            onValueChange={v => setOwnerAvailable('owner1', v)}
            trackColor={{ true: '#34C759' }}
          />
        </View>
        <View style={[styles.ownerRow, styles.ownerRowDivider]}>
          <Text style={styles.ownerLabel}>Ginger</Text>
          <Switch
            value={owner2}
            onValueChange={v => setOwnerAvailable('owner2', v)}
            trackColor={{ true: '#34C759' }}
          />
        </View>
        {!bothAvailable && (
          <Text style={styles.unavailableNote}>Door locked — both owners must be available</Text>
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Manual Control</Text>
        <TouchableOpacity
          style={[styles.button, styles.openButton, !bothAvailable && styles.buttonDisabled]}
          onPress={() => sendCommand('open')}
          disabled={!bothAvailable}
        >
          <Text style={styles.buttonText}>Open Door</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.button, styles.closeButton]}
          onPress={() => sendCommand('close')}
        >
          <Text style={styles.buttonText}>Close Door</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.button, styles.stopButton]}
          onPress={() => sendCommand('stop')}
        >
          <Text style={styles.buttonText}>Emergency Stop</Text>
        </TouchableOpacity>
      </View>

    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F2F2F7',
    padding: 16,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
    marginTop: 8,
  },
  title: {
    fontSize: 34,
    fontWeight: '700',
    color: '#000',
  },
  navHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    marginTop: 4,
  },
  navSeparator: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: '#C6C6C8',
    marginHorizontal: -16,
    marginBottom: 24,
  },
  backButton: {
    flexDirection: 'row',
    alignItems: 'center',
    minWidth: 80,
  },
  backText: {
    color: '#007AFF',
    fontSize: 17,
  },
  navTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: '#000',
  },
  navSpacer: {
    minWidth: 80,
  },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    color: '#8E8E93',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 6,
    marginLeft: 4,
  },
  sectionDesc: {
    fontSize: 13,
    color: '#8E8E93',
    lineHeight: 18,
    marginBottom: 8,
    marginLeft: 4,
    marginTop: -2,
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#8E8E93',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 12,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  statusDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  statusText: {
    fontSize: 18,
    fontWeight: '600',
    flex: 1,
    textTransform: 'capitalize',
    color: '#000',
  },
  pctText: {
    fontSize: 16,
    color: '#8E8E93',
  },
  ownerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  ownerRowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E5E5EA',
    marginTop: 12,
    paddingTop: 12,
  },
  ownerLabel: {
    fontSize: 17,
    color: '#000',
  },
  allLedsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 4,
  },
  allLedsLabel: {
    fontSize: 17,
    fontWeight: '600',
    color: '#000',
  },
  ledLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  ledDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  unavailableNote: {
    marginTop: 12,
    fontSize: 13,
    color: '#FF3B30',
    textAlign: 'center',
  },
  signalStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  signalDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  signalLabel: {
    fontSize: 15,
    fontWeight: '500',
  },
  settingsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  settingsRowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  settingsIconBg: {
    width: 30,
    height: 30,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  settingsRowText: {
    fontSize: 17,
    color: '#000',
  },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: '#E5E5EA',
    borderRadius: 8,
    padding: 2,
    marginTop: 12,
    marginBottom: 8,
  },
  segment: {
    flex: 1,
    paddingVertical: 6,
    alignItems: 'center',
    borderRadius: 6,
  },
  segmentActive: {
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOpacity: 0.1,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
  },
  segmentText: {
    fontSize: 13,
    fontWeight: '500',
    color: '#8E8E93',
  },
  segmentTextActive: {
    color: '#000',
    fontWeight: '600',
  },
  button: {
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 10,
  },
  openButton: {
    backgroundColor: '#34C759',
  },
  closeButton: {
    backgroundColor: '#FF3B30',
  },
  stopButton: {
    backgroundColor: '#FF9500',
  },
  buttonDisabled: {
    backgroundColor: '#C7C7CC',
  },
  buttonText: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '600',
  },
});
