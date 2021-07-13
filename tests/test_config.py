import os
import shutil

import pytest
import six
import yaml

import user_sync.rules as rules
from tests.util import make_dict, merge_dict, compare_iter
from user_sync.config import ConfigFileLoader, ConfigLoader, DictConfig
from user_sync.connector.directory import DirectoryConnector
from user_sync.connector.directory_ldap import LDAPDirectoryConnector
from user_sync.error import AssertionException

rules_defaults = rules.RuleProcessor.default_options.copy()


def reset_rule_options():
    # Reset the ruleprocessor options since get_rule_options is a destructive method
    # If options are not reset, subsuent tests (rules.py) may fail
    rules.RuleProcessor.default_options = rules_defaults.copy()


@pytest.fixture()
def cleanup():
    # Failsafe in case of failed test - resets options
    yield
    reset_rule_options()


@pytest.fixture
def config_files(fixture_dir, tmpdir):
    config_files = {
        'ldap': 'connector-ldap.yml',
        'umapi': 'connector-umapi.yml',
        'root_config': 'user-sync-config.yml',
        'extension': 'extension-config.yml',
    }

    for k, n in six.iteritems(config_files):
        shutil.copy(os.path.join(fixture_dir, n), tmpdir.dirname)
        config_files[k] = os.path.join(tmpdir.dirname, n)
    return config_files


@pytest.fixture
def modify_config(config_files):
    def _modify_config(name, key, value):
        path = config_files[name]
        conf = yaml.safe_load(open(path))
        merge_dict(conf, make_dict(key, value))
        yaml.dump(conf, open(path, 'w'))
        return path

    return _modify_config


# A shortcut for root
@pytest.fixture
def modify_root_config(modify_config):
    def _modify_root_config(key, value):
        return modify_config('root_config', key, value)

    return _modify_root_config

# A shortcut for loading the config file
@pytest.fixture
def default_args(cli_args, config_files):
    return cli_args({'config_filename': config_files['root_config']})


class TestConfigLoader():

    # todo: implement test_load_main_config
    def test_load_main_config(self):
        pass

    def test_load_invocation_options(self, default_args, modify_root_config):

        # root_config_file = config_files['root_config']
        # args = cli_args({'config_filename': root_config_file})

        # Default was 'preserve.'
        modify_root_config(['invocation_defaults', 'adobe_only_user_action'], 'delete')
        # Default was 'all.'
        modify_root_config(['invocation_defaults', 'adobe_users'], ['mapped'])
        # Default was 'ldap.'
        modify_root_config(['invocation_defaults', 'connector'], ['okta'])
        # Default was 'utf8.'
        modify_root_config(['invocation_defaults', 'encoding_name'], 'ascii')
        # Default was 'False.'
        modify_root_config(['invocation_defaults', 'process_groups'], True)
        # Default was 'False.'
        modify_root_config(['invocation_defaults', 'test_mode'], True)
        # Default was 'False.'
        modify_root_config(['invocation_defaults', 'update_user_info'], True)
        # Default was None.
        modify_root_config(['invocation_defaults', 'user_filter'], 'b.*@forxampl.com')
        # Default was 'all.'
        modify_root_config(['invocation_defaults', 'users'], ['mapped'])
        modify_root_config(['invocation_defaults', 'config_filename'], 'user-sync-config.yml')

        # Check that the root options were loaded correctly
        options = ConfigLoader(default_args).load_invocation_options()
        assert options['adobe_only_user_action'] == ['delete']
        assert options['adobe_users'] == ['mapped']
        assert options['connector'] == ['okta']
        assert options['encoding_name'] == 'ascii'
        assert options['process_groups'] is True
        assert options['test_mode'] is True
        assert options['update_user_info'] is True
        assert options['user_filter'] == 'b.*@forxampl.com'
        assert options['users'] == ['mapped']

        # Default was None
        modify_root_config(['invocation_defaults', 'adobe_only_user_list'], 'adobe_only_user_list.csv')

        options = ConfigLoader(default_args).load_invocation_options()
        assert options['adobe_only_user_list'] == 'adobe_only_user_list.csv'

        # Default was 'sync.'
        modify_root_config(['invocation_defaults', 'adobe_only_user_list'], None)
        modify_root_config(['invocation_defaults', 'strategy'], 'push')

        options = ConfigLoader(default_args).load_invocation_options()
        assert options['strategy'] == 'push'
        assert options['adobe_only_user_action'] is None
        assert options['adobe_only_user_list'] is None

    def test_get_umapi_options(self, default_args, config_files, modify_root_config):
        umapi_config = config_files['umapi']

        tmp_folder = os.path.dirname(umapi_config)
        with open(os.path.join(tmp_folder, 'private.key'), 'w') as key:
            key.write("data")

        # tests a single primary umapi configuration
        config_loader = ConfigLoader(default_args)
        primary, secondary = config_loader.get_umapi_options()
        assert {'server', 'enterprise'} <= set(primary)
        assert secondary == {}

        # tests secondary connector
        modify_root_config(['adobe_users', 'connectors', 'umapi'], [umapi_config, {'secondary_console': umapi_config}])
        config_loader = ConfigLoader(default_args)
        primary, secondary = config_loader.get_umapi_options()
        assert {'server', 'enterprise'} <= set(primary)
        assert 'secondary_console' in secondary

        # tests secondary umapi configuration assertion
        modify_root_config(['adobe_users', 'connectors', 'umapi'], [{'primary': umapi_config}, umapi_config])
        config_loader = ConfigLoader(default_args)
        with pytest.raises(AssertionException) as error:
            config_loader.get_umapi_options()
        assert "Secondary umapi configuration found with no prefix:" in str(error.value)

        # tests v1 assertion
        modify_root_config(['dashboard'], {})
        config_loader = ConfigLoader(default_args)
        with pytest.raises(AssertionException) as error:
            config_loader.get_umapi_options()
        assert "Your main configuration file is still in v1 format." in str(error.value)

    def test_get_directory_connector_module_name(self, default_args, config_files):
        config_loader = ConfigLoader(default_args)
        options = config_loader.invocation_options
        options['stray_list_input_path'] = 'something'
        assert not config_loader.get_directory_connector_module_name()

        options['directory_connector_type'] = 'csv'
        options['stray_list_input_path'] = None
        expected = 'user_sync.connector.directory_csv'
        assert config_loader.get_directory_connector_module_name() == expected

        options['directory_connector_type'] = None
        assert not config_loader.get_directory_connector_module_name()

    def test_get_directory_connector_configs(self, default_args, config_files):
        config_loader = ConfigLoader(default_args)
        config_loader.get_directory_connector_configs()

        # Test method to verify path is the value of the 'ldap' key
        expected_file_path = config_loader.main_config.value['directory_users']['connectors']['ldap']
        assert expected_file_path == config_files['ldap']

        # Test method to verify 'okta', 'csv', 'ldap' are in the accessed_keys set
        result = (config_loader.main_config.child_configs.get('directory_users').child_configs['connectors'].accessed_keys)
        assert result == {'okta', 'adobe_console', 'csv', 'ldap'}

        # Check for unknown conector type
        default_args['connector'] = ['bad_connector']
        pytest.raises(AssertionException, ConfigLoader, default_args)

    # todo: implement test_get_directory_connector_options
    def test_get_directory_connector_options(self):
        pass

    def test_load_directory_groups(self, default_args, modify_root_config):

        modify_root_config(['directory_users', 'groups'], [{
            'directory_group': 'Directory Group',
            'adobe_groups': ['Acrobat Users']}
        ])

        result = ConfigLoader(default_args).load_directory_groups()
        assert 'Directory Group' in result
        assert isinstance(result['Directory Group'][0], rules.AdobeGroup)

        modify_root_config(['directory_users', 'groups'], [])
        result = ConfigLoader(default_args).load_directory_groups()
        assert result == {}

        modify_root_config(['directory_users', 'groups'], [{
            'directory_group': 'DIR-1',
            'adobe_groups': ['']}])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).load_directory_groups()
        assert 'Bad adobe group: "" in directory group: "DIR-1"' in str(error.value)

        modify_root_config(['directory_users', 'groups'], [{
            'directory_group': None,
            'adobe_groups': ['Group']}])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).load_directory_groups()
        assert 'Value not found for key: directory_group' in str(error.value)

        modify_root_config(['directory'], {})
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).load_directory_groups()
        assert "Your main configuration file is still in v1 format.  Please convert it to v2." in str(error.value)

    def test_get_directory_extension_option(self, default_args, modify_config, modify_root_config, config_files):
        # case 1: When there is no change in the user sync config file
        # getting the user-sync file from the set of config files

        config_loader = ConfigLoader(default_args)
        assert config_loader.get_directory_extension_options() == {}

        # case 2: When there is an extension file link in the user-sync-config file
        with open(config_files['extension']) as f:
            default_content = yaml.load(f)
        modify_root_config(['directory_users', 'extension'], 'extension-config.yml')
        config_loader = ConfigLoader(default_args)
        assert(config_loader.get_directory_extension_options().value == default_content)

        # raise assertionerror if after mapping hook has nothing
        modify_config('extension', ['after_mapping_hook'], None)
        pytest.raises(AssertionError, config_loader.get_directory_extension_options)

        # check for the string under after mapping hook
        modify_config('extension', ['after_mapping_hook'], 'print hello ')
        options = {
            'after_mapping_hook': 'print hello ',
            'extended_adobe_groups': ['Company 1 Users', 'Company 2 Users'],
            'extended_attributes': ['bc', 'subco']
        }
        assert config_loader.get_directory_extension_options().value == options

    def test_get_rule_options_add(self, cleanup, modify_root_config, default_args):

        # Modify these values in the root_config file (user-sync-config.yml)
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['adobe_users', 'exclude_identity_types'], ['adobeID'])
        modify_root_config(['directory_users', 'default_country_code'], "EU")
        modify_root_config(['directory_users', 'user_identity_type'], "enterpriseID")
        modify_root_config(['directory_users', 'additional_groups'], [{
            'source': 'ACL-(.+)',
            'target': 'ACL-Grp-(\\1)'}])
        modify_root_config(['directory_users', 'group_sync_options'], {
            'auto_create': True})
        modify_root_config(['directory_users', 'groups'], [{
            'directory_group': 'DIR-1',
            'adobe_groups': ['GRP-1']}, {
            'directory_group': 'DIR-2',
            'adobe_groups': ['GRP-2.1', 'GRP-2.2']}])
        modify_root_config(['limits', 'max_adobe_only_users'], '300')

        config_loader = ConfigLoader(default_args)
        options = config_loader.invocation_options
        options['exclude_adobe_groups'] = ['one', 'two']
        options['exclude_users'] = ['UserA', 'UserB']
        options['directory_group_mapped'] = True
        options['adobe_group_mapped'] = True
        result = config_loader.get_rule_options()

        # Assert the values made it into the options dictionary and are successfully returned
        assert result['new_account_type'] == 'enterpriseID'
        assert result['default_country_code'] == 'EU'
        assert result['additional_groups'][0]['source'].pattern == 'ACL-(.+)'
        assert result['directory_group_filter'] == {'DIR-1', 'DIR-2'}
        assert result['exclude_adobe_groups'] == ['one', 'two']
        assert result['exclude_users'] == ['UserA', 'UserB']
        assert result['max_adobe_only_users'] == 300

    def test_get_rule_options_exceptions(self, cleanup, modify_root_config, default_args):

        # Set an exclude_identity_types to a list with an invalid id type to throw an error
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['adobe_users', 'exclude_identity_types'], ['adobeID', 'UnknownID'])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'Illegal value in exclude_identity_types: Unrecognized identity type: "UnknownID"' in str(error.value)
        # Reset exclude_identity_types and set additional_groups to an invalid key:value

        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['adobe_users', 'exclude_identity_types'], ['adobeID'])
        modify_root_config(['directory_users', 'additional_groups'], [{'nothing': None}])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'Additional group rule error:' in str(error.value)

        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['directory_users', 'additional_groups'], [{
            'source': 'ACL-(.+)',
            'target': 'ACL-Grp-(\\1)'}])
        modify_root_config(['adobe_users', 'exclude_adobe_groups'], [''])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'Illegal value for exclude_groups in config file:  (Not a legal group name)' in str(error.value)

        # Reset additional groups and set regex to invalid regex pattern
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['adobe_users', 'exclude_adobe_groups'], ['null'])
        modify_root_config(['adobe_users', 'exclude_users'], ['.***@error.com*.'])
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'Illegal regular expression (.***@error.com*.) in exclude_identity_types' in str(error.value)

        # Set directory_users to None
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['directory_users'], None)
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert "'directory_users' must be specified" in str(error.value)

    def test_get_rule_options_regex(self, cleanup, modify_root_config, default_args):

        # Set exclude_users to a regex to verify it compiles correctly
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['adobe_users', 'exclude_users'], ['.*@special.com', "freelancer-[0-9]+.*"])
        result = ConfigLoader(default_args).get_rule_options()
        assert result['exclude_users'][0].pattern == '\\A.*@special.com\\Z'
        assert result['exclude_users'][1].pattern == '\\Afreelancer-[0-9]+.*\\Z'

    def test_get_rule_options_percent(self, cleanup, modify_root_config, default_args):

        # Set to a valid percentage value and verify it saves as a percentage value
        reset_rule_options()  # Reset the ruleprocessor
        modify_root_config(['limits', 'max_adobe_only_users'], '80%')
        result = ConfigLoader(default_args).get_rule_options()
        assert result['max_adobe_only_users'] == '80%'

        # Set a percentage higher than 100% to raise an exception
        modify_root_config(['limits', 'max_adobe_only_users'], '101%')
        reset_rule_options()  # Reset the ruleprocessor
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'max_adobe_only_users value must be less or equal than 100%' in str(error.value)

        # Set the value to max_adobe_only_users to a string to raise an exception
        modify_root_config(['limits', 'max_adobe_only_users'], 'one-hundred')
        reset_rule_options()  # Reset the ruleprocessor
        with pytest.raises(AssertionException) as error:
            ConfigLoader(default_args).get_rule_options()
        assert 'Unable to parse max_adobe_only_users value. Value must be a percentage or an integer.' in str(
            error.value)

    def test_get_rule_options_extension(self, cleanup, modify_root_config, default_args, modify_config):

        # Set the extension-config file to be called in user-sync-config. Assert after_mapping_hook is processed correctly
        modify_root_config(['directory_users', 'extension'], 'extension-config.yml')
        reset_rule_options()  # Reset the ruleprocessor
        config_loader = ConfigLoader(default_args)
        result = config_loader.get_rule_options()
        expected = (
            'bc', 'subco', None, 0, 2, 'country', 'Company 1', 'Company 1 Users', 'Company 2', 'Company 2 Users')
        result = result['after_mapping_hook'].co_consts
        assert compare_iter(result, expected)

        # Modify the extension-config file to call an extended_adobe_groups to a blank value to raise an exception
        modify_config('extension', ['extended_adobe_groups'], '')
        reset_rule_options()  # Reset the ruleprocessor
        with pytest.raises(AssertionException) as error:
            config_loader = ConfigLoader(default_args)
            config_loader.get_rule_options()
        assert 'Extension contains illegal extended_adobe_group spec: ' in str(error.value)

    def test_combine_dicts(self, default_args, modify_config, modify_root_config):

        config_loader = ConfigLoader(default_args)
        # Create a dummy dict

        dict1 = {
            'server': {
                'host': 'dummy1-stage.adobe.io',
                'ims_host': 'ims-na1-stg1.adobelogin.com',
                'test': 'test'},
            'enterprise': {
                'org_id': 'DXXXXXXX1A20A49412A@AdobeOrg',
                'api_key': 'XXXXXXXXXX4dba226cba72cac',
                'client_secret': '5XXXXXXXXXX4549-8ac1-0d607ee558c3',
                'tech_acct': 'XXXXXXXXX20A494216@techacct.adobe.com',
                'priv_key_path': 'private.key'}}
        dict2 = {
            'server': {
                'host': 'dummy2-stage.adobe.io',
                'ims_host': 'ims-na1-stg1.adobelogin.com'},
            'enterprise': {
                'mike': 'mike',
                'org_id': 'DXXXXXXX1A20A49412A@AdobeOrg',
                'api_key': 'XXXXXXXXXX4dba226cba72cac',
                'client_secret': '5XXXXXXXXXX4549-8ac1-0d607ee558c3',
                'tech_acct': 'XXXXXXXXX20A494216@techacct.adobe.com',
                'priv_key_path': 'rivate.key'}}


        result = config_loader.combine_dicts([dict1, dict2])
        dict2['server']['test'] = 'test'
        assert dict2 == result

    def test_adobe_users_config(self, default_args, config_files, modify_root_config):

        # test default
        config_loader = ConfigLoader(default_args)
        options = config_loader.load_invocation_options()
        assert 'adobe_users' in options
        assert options['adobe_users'] == ['all']

        # test default invocation
        modify_root_config(['invocation_defaults', 'adobe_users'], "mapped")
        config_loader = ConfigLoader(default_args)
        options = config_loader.load_invocation_options()
        assert 'adobe_users' in options
        assert options['adobe_users'] == ['mapped']

        # test command line param
        modify_root_config(['invocation_defaults', 'adobe_users'], "all")
        default_args.update({
            'config_filename': config_files['root_config'],
            'adobe_users': ['mapped']})
        config_loader = ConfigLoader(default_args)
        options = config_loader.load_invocation_options()
        assert 'adobe_users' in options
        assert options['adobe_users'] == ['mapped']


#
#
class TestLDAPConfig():
    """
    Testing of config options for ldap connector
    """

    def test_twostep_config(self, cli_args, config_files, modify_config):
        def load_ldap_config_options(args):

            config_loader = ConfigLoader(args)
            dc_mod_name = config_loader.get_directory_connector_module_name()
            dc_mod = __import__(dc_mod_name, fromlist=[''])
            dc = DirectoryConnector(dc_mod)
            dc_config_options = config_loader.get_directory_connector_options(dc.name)
            caller_config = DictConfig('%s configuration' % dc.name, dc_config_options)
            return LDAPDirectoryConnector.get_options(caller_config)

        modify_config('ldap', ['two_steps_lookup'], {})
        args = cli_args({
            'config_filename': config_files['root_config']})

        # test invalid "two_steps_lookup" config
        with pytest.raises(AssertionException):
            load_ldap_config_options(args)

        # test valid "two_steps_lookup" config with "group_member_filter_format" still set
        modify_config('ldap', ['two_steps_lookup', 'group_member_attribute_name'], 'member')
        with pytest.raises(AssertionException):
            load_ldap_config_options(args)

        # test valid "two_steps_lookup" setup
        modify_config('ldap', ['two_steps_lookup', 'group_member_attribute_name'], 'member')
        modify_config('ldap', ['group_member_filter_format'], "")
        options = load_ldap_config_options(args)
        assert 'two_steps_enabled' in options
        assert 'two_steps_lookup' in options
        assert 'group_member_attribute_name' in options['two_steps_lookup']
        assert options['two_steps_lookup']['group_member_attribute_name'] == 'member'


class TestConfigFileLoader():
    """
    Tests for ConfigFileLoader
    """

    def test_load_root(self, config_files):
        """Load root config file and test for presence of root-level keys"""
        config = ConfigFileLoader.load_root_config(config_files['root_config'])
        assert isinstance(config, dict)
        assert ('adobe_users' in config and 'directory_users' in config and
                'logging' in config and 'limits' in config and
                'invocation_defaults' in config)

    def test_max_adobe_percentage(self, cleanup, cli_args, modify_root_config):
        root_config_file = modify_root_config(['limits', 'max_adobe_only_users'], "50%")
        config = ConfigFileLoader.load_root_config(root_config_file)
        assert ('limits' in config and 'max_adobe_only_users' in config['limits'] and
                config['limits']['max_adobe_only_users'] == "50%")

        args = cli_args({'config_filename': root_config_file})
        reset_rule_options()  # Reset the ruleprocessor
        options = ConfigLoader(args).get_rule_options()
        assert 'max_adobe_only_users' in options and options['max_adobe_only_users'] == '50%'

        modify_root_config(['limits', 'max_adobe_only_users'], "error%")
        reset_rule_options()  # Reset the ruleprocessor
        with pytest.raises(AssertionException):
            ConfigLoader(args).get_rule_options()

    def test_additional_groups_config(self, cleanup, cli_args, modify_root_config):
        addl_groups = [
            {
                "source": r"ACL-(.+)",
                "target": r"ACL-Grp-(\1)"},
            {
                "source": r"(.+)-ACL",
                "target": r"ACL-Grp-(\1)"},
        ]
        root_config_file = modify_root_config(['directory_users', 'additional_groups'], addl_groups)
        config = ConfigFileLoader.load_root_config(root_config_file)
        assert ('additional_groups' in config['directory_users'] and
                len(config['directory_users']['additional_groups']) == 2)

        args = cli_args({
            'config_filename': root_config_file})

        reset_rule_options()  # Reset the ruleprocessor
        options = ConfigLoader(args).get_rule_options()
        assert addl_groups[0]['source'] in options['additional_groups'][0]['source'].pattern
        assert addl_groups[1]['source'] in options['additional_groups'][1]['source'].pattern
