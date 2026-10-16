package portfolio;

import ibcalpha.ibc.DefaultLoginManager;
import ibcalpha.ibc.DefaultMainWindowManager;
import ibcalpha.ibc.DefaultSettings;
import ibcalpha.ibc.DefaultTradingModeManager;
import ibcalpha.ibc.IbcTws;
import ibcalpha.ibc.LoginManager;
import ibcalpha.ibc.MainWindowManager;
import ibcalpha.ibc.SessionManager;
import ibcalpha.ibc.Settings;
import ibcalpha.ibc.TradingModeManager;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Starts IB Gateway through IBC with the username and password read from stdin (two lines),
 * so they are never in a file or on the command line. Usage: StdinLauncher <config.ini> <live|paper>
 */
public class StdinLauncher {
    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String username = in.readLine();
        String password = in.readLine();
        if (username == null) username = "";
        if (password == null) password = "";

        SessionManager.initialise(true);  // Gateway, not TWS
        Settings.initialise(new DefaultSettings(args[0]));
        LoginManager.initialise(new DefaultLoginManager(username, password));
        MainWindowManager.initialise(new DefaultMainWindowManager());
        TradingModeManager.initialise(new DefaultTradingModeManager(args[1]));
        IbcTws.load();
    }
}
