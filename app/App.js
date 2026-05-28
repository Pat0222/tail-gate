import { useEffect, useState } from 'react';
import { StyleSheet, Text, View, Switch, TouchableOpacity, SafeAreaView, ActivityIndicator, Platform } from 'react-native';
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
  const [doorState, setDoorState] = useState('unknown');
  const [openPct, setOpenPct]     = useState(0);
  const [owner1, setOwner1]       = useState(false);
  const [owner2, setOwner2]       = useState(false);

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

    registerForPushNotifications().then(token => {
      if (token) {
        const key = token.replace(/[[\]]/g, '');
        set(ref(db, `push_tokens/${key}`), token);
      }
    });

    return () => { unsubDoor(); unsubOwners(); };
  }, []);

  const setOwnerAvailable = (owner, value) => {
    set(ref(db, `owners/${owner}`), { available: value });
  };

  const sendCommand = (cmd) => {
    set(ref(db, 'command'), cmd);
  };

  const isMoving    = doorState === 'partially_open' || doorState === 'partially_closed';
  const statusColor = DOOR_COLORS[doorState] ?? '#8E8E93';
  const statusLabel = isMoving
    ? (doorState === 'partially_open' ? 'Opening...' : 'Closing...')
    : doorState.replace(/_/g, ' ');
  const bothAvailable = owner1 && owner2;

  return (
    <SafeAreaView style={styles.container}>

      <Text style={styles.title}>Puppy Play Time</Text>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Door Status</Text>
        <View style={styles.statusRow}>
          {isMoving
            ? <ActivityIndicator size="small" color={statusColor} />
            : <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
          }
          <Text style={[styles.statusText, isMoving && { color: statusColor }]}>{statusLabel}</Text>
          <Text style={styles.pctText}>{openPct}% open</Text>
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
  title: {
    fontSize: 34,
    fontWeight: '700',
    marginBottom: 20,
    marginTop: 8,
    color: '#000',
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
  unavailableNote: {
    marginTop: 12,
    fontSize: 13,
    color: '#FF3B30',
    textAlign: 'center',
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
